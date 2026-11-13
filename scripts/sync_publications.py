#!/usr/bin/env python3
"""Generate publication entries and open-access PDFs from an OpenAlex profile.

The script is idempotent: existing DOIs, titles and slugs are never overwritten.
Dry-run is the default; pass --apply to write files.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import rich_click as click
from curl_cffi import requests as curl_requests

LOG = logging.getLogger("sync-publications")

API_ROOT = "https://api.openalex.org"
DEFAULT_AUTHOR = "https://openalex.org/authors/A5004170724"
DEFAULT_AUTHOR_NAME = "Robert A. Petit III"
SUFFIX_LABELS = {"Jr": "Jr.", "Sr": "Sr.", "II": "2nd", "III": "3rd", "IV": "4th"}
USER_AGENT = "robertpetit.com-publication-sync/1.0 (+https://www.robertpetit.com)"

DEFAULT_TYPES = "article,conference-paper,book-chapter,review"
PDF_MAGIC = b"%PDF-"
PDF_MIN_BYTES = 10_000
PDF_MAX_BYTES = 60_000_000
MAX_AUTHORS = 20
OPENALEX_AUTHOR_CAP = 100
CROSSREF_ROOT = "https://api.crossref.org/works"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "their",
    "to",
    "via",
    "with",
}

SELECT_FIELDS = ",".join(
    [
        "abstract_inverted_index",
        "authorships",
        "best_oa_location",
        "biblio",
        "content_urls",
        "doi",
        "id",
        "ids",
        "is_retracted",
        "keywords",
        "locations",
        "open_access",
        "primary_location",
        "primary_topic",
        "publication_date",
        "publication_year",
        "title",
        "type",
    ]
)


@dataclass(frozen=True)
class ExistingRecord:
    """A stored entry relevant to duplicate and preprint decisions."""

    path: Path
    doi: str
    version: int
    preprint: bool


@dataclass(frozen=True)
class ExistingIndex:
    """DOIs, titles and slugs already owned by the site."""

    dois: set[str]
    titles: set[str]
    slugs: set[str]
    by_title: dict[str, ExistingRecord]


@dataclass
class Entry:
    """One rendered publication waiting to be written."""

    slug: str
    doi: str
    title: str
    front_matter: str
    pdf_urls: list[str]
    pdf_saved: bool = False


def ascii_fold(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def normalize_doi(value: str) -> str:
    doi = value.strip().strip('"').lower()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi)
    return doi.rstrip(".")


def normalize_title(value: str) -> str:
    text = ascii_fold(value).lower()
    text = re.sub(
        r"^(author response|erratum to|abstract|correction to)\s*:?\s*", "", text
    )
    return re.sub(r"[^a-z0-9]+", "", text)


def slugify_title(year: int, title: str, max_len: int = 72) -> str:
    """Build an SEO slug with the publication year as the leading token."""
    folded = ascii_fold(title).lower().replace("&", " and ")
    folded = folded.replace("'", "").replace("’", "")
    words = [word for word in re.split(r"[^a-z0-9]+", folded) if word]
    words = [
        word
        for word in words
        if (word not in STOPWORDS and len(word) > 1) or word.isdigit()
    ]
    if not words:
        words = ["publication"]

    prefix = f"{year}-"
    budget = max_len - len(prefix)
    kept: list[str] = []
    for word in words:
        candidate = "-".join([*kept, word])
        if len(candidate) > budget:
            break
        kept.append(word)
    if not kept:
        kept = [words[0][:budget].rstrip("-") or "publication"]
    return f"{prefix}{'-'.join(kept)}"


def unique_slug(base: str, taken: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in taken:
        candidate = f"{base}-{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for position in positions:
            positioned.append((position, word))
    positioned.sort()
    return html.unescape(" ".join(word for _, word in positioned))


def clean_title(value: str) -> str:
    title = html.unescape(value).strip()
    title = re.sub(r"^\d{1,4}\.\s+", "", title)
    return re.sub(r"\s+([:;,.!?])", r"\1", title)


def strip_section_labels(text: str) -> str:
    text = text.strip()
    previous = None
    while text != previous:
        previous = text
        text = re.sub(r"^abstract\s*:?\s+", "", text, flags=re.IGNORECASE)
    return re.sub(
        r"^(?:background|methods?|objectives?|results?|conclusions?)\s*:?\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )


def clean_abstract(text: str) -> str:
    return strip_section_labels(text)


def summarize(abstract: str, title: str, limit: int = 200) -> str:
    text = strip_section_labels(re.sub(r"\s+", " ", abstract))
    if text:
        sentence = re.split(r"(?<=[.!?])\s+", text)[0].strip()
    else:
        sentence = title.strip()
    if len(sentence) <= limit:
        return sentence
    cut = sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut}…"


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_author_name(display_name: str) -> str:
    if display_name.strip() == "et al.":
        return "et al."
    tokens = display_name.replace(".", ". ").split()
    if not tokens:
        return display_name
    suffix = ""
    if tokens[-1].rstrip(".") in SUFFIX_LABELS:
        suffix = f", {SUFFIX_LABELS[tokens.pop().rstrip('.')]}"
    family = tokens[-1]
    initials = [
        f"{token[0]}." for token in tokens[:-1] if token and token[0].isalpha()
    ]
    return f"{family}, {' '.join(initials)}{suffix}".strip()


def profile_author_match(name: str, author_name: str) -> bool:
    tokens = [
        token
        for token in author_name.split()
        if token.rstrip(".") not in SUFFIX_LABELS
    ]
    if not tokens:
        return False
    family = tokens[-1].lower()
    given_initial = tokens[0][0].lower()
    lowered = name.lower()
    parts = re.findall(r"[a-z]+", lowered)
    return family in parts and any(part.startswith(given_initial) for part in parts)


def crossref_person_name(person: dict[str, Any]) -> str:
    given = (person.get("given") or "").strip()
    family = (person.get("family") or "").strip()
    suffix = (person.get("suffix") or "").strip()
    if family in SUFFIX_LABELS and given:
        parts = given.split()
        family = parts[-1]
        given = " ".join(parts[:-1])
        suffix = person["family"]
    return (person.get("name") or " ".join(filter(None, [given, family, suffix]))).strip()


def crossref_author_names(doi: str, timeout: int) -> list[str]:
    response = requests.get(
        f"{CROSSREF_ROOT}/{doi}",
        headers={
            "User-Agent": f"{USER_AGENT} (mailto:rpetit3@gmail.com)",
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    people = (response.json().get("message") or {}).get("author") or []
    names: list[str] = []
    for person in people:
        name = crossref_person_name(person)
        if name:
            names.append(name)
    if names:
        LOG.info("Used Crossref author list for %s", doi)
    return names


def author_pairs(
    work: dict[str, Any], author_id: str, author_name: str, timeout: int
) -> list[tuple[str, bool]]:
    """Return (name, is_profile_author), completing capped OpenAlex lists."""
    authorships = work.get("authorships") or []
    pairs: list[tuple[str, bool]] = []
    for authorship in authorships:
        author = authorship.get("author") or {}
        name = author.get("display_name") or author.get("raw_author_name") or ""
        if name:
            pairs.append((name, (author.get("id") or "").rsplit("/", 1)[-1] == author_id))

    if len(pairs) < OPENALEX_AUTHOR_CAP and any(is_me for _, is_me in pairs):
        return pairs

    doi = normalize_doi(str(work.get("doi") or ""))
    try:
        names = crossref_author_names(doi, timeout)
    except Exception as error:  # noqa: BLE001 - fall back to OpenAlex data
        LOG.warning("Crossref author lookup failed for %s: %s", doi, error)
        names = []
    if names:
        pairs = [(name, profile_author_match(name, author_name)) for name in names]
    if not any(is_me for _, is_me in pairs):
        pairs.append((author_name, True))
    return pairs


def render_citation(
    names: list[str],
    title: str,
    journal: str,
    biblio: dict[str, str],
    year: int,
) -> str:
    formatted = [name for name in (render_author_name(item) for item in names) if name]
    if len(formatted) > 6:
        byline = ", ".join(formatted[:6]) + ", et al."
    else:
        byline = ", ".join(formatted)
    if not byline:
        byline = "Anonymous."

    venue = journal.strip("*")
    volume = biblio.get("volume") or ""
    issue = biblio.get("issue") or ""
    pages = biblio.get("first_page") or ""
    last_page = biblio.get("last_page") or ""
    if pages and last_page:
        pages = f"{pages}-{last_page}"
    location = venue
    if volume:
        location += f" {volume}"
    if issue:
        location += f"({issue})"
    if pages:
        location += f", {pages}"
    location = location.strip()
    return f"{byline} {title}. {location} ({year})."


def is_pdf(blob: bytes) -> bool:
    return blob.startswith(PDF_MAGIC) and len(blob) >= PDF_MIN_BYTES


PREPRINT_DOI_PREFIXES = (
    "10.1101/",
    "10.21203/",
    "10.22541/",
    "10.31219/",
    "10.36227/",
    "10.48550/",
    "10.7287/",
)
PREPRINT_VENUES = re.compile(
    r"biorxiv|medrxiv|research square|ssrn|arxiv|techrxiv|authorea|preprints",
    re.IGNORECASE,
)


def is_preprint(doi: str, journal: str) -> bool:
    return doi.startswith(PREPRINT_DOI_PREFIXES) or bool(
        PREPRINT_VENUES.search(journal)
    )


DOI_VERSION = re.compile(r"^(.*?)\.(\d+)$")


def doi_version(doi: str) -> tuple[str, int] | None:
    match = DOI_VERSION.match(doi)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def is_numbered_abstract(work: dict[str, Any]) -> bool:
    """Conference poster abstracts: numbered title plus supplemental pages."""
    title = str(work.get("title") or "")
    pages = str((work.get("biblio") or {}).get("first_page") or "")
    return bool(re.match(r"^\d{1,4}\.\s", title) and re.match(r"^[Ss]\d", pages))


def load_existing(content_dir: Path, pdf_dir: Path) -> ExistingIndex:
    dois: set[str] = set()
    titles: set[str] = set()
    slugs: set[str] = set()
    by_title: dict[str, ExistingRecord] = {}

    for path in sorted(content_dir.glob("*.md")):
        slugs.add(path.stem)
        try:
            raw = path.read_text(encoding="utf-8")
            front_matter = raw.split("+++", 2)[1]
            data = tomllib.loads(front_matter)
        except (OSError, IndexError, tomllib.TOMLDecodeError) as error:
            LOG.warning("Could not parse %s: %s", path, error)
            continue
        doi = normalize_doi(str(data.get("doi", "")))
        if doi:
            dois.add(doi)
        title = normalize_title(str(data.get("title", "")))
        if title:
            titles.add(title)
            preprint = bool(data.get("preprint")) or is_preprint(
                doi, str(data.get("journal", ""))
            )
            version = int(data.get("preprint_version") or 0)
            if not version:
                parsed = doi_version(doi)
                version = parsed[1] if parsed else 0
            by_title[title] = ExistingRecord(
                path=path, doi=doi, version=version, preprint=preprint
            )

    for path in pdf_dir.glob("*.pdf"):
        slugs.add(path.stem)
    return ExistingIndex(
        dois=dois,
        titles=titles,
        slugs=slugs,
        by_title=by_title,
    )


def author_id_from_profile(profile: str) -> str:
    match = re.search(r"(A\d+)", profile)
    if not match:
        raise click.BadParameter(f"no OpenAlex author ID in {profile!r}")
    return match.group(1)


def api_headers(api_key: str | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def fetch_works(author_id: str, api_key: str | None, types: list[str]) -> list[dict]:
    works: list[dict] = []
    cursor = "*"
    page = 0
    while cursor and page < 20:
        page += 1
        params = {
            "filter": f"authorships.author.id:{author_id},type:{'|'.join(types)}",
            "per-page": 200,
            "cursor": cursor,
            "select": SELECT_FIELDS,
            "mailto": "rpetit3@gmail.com",
        }
        response = requests.get(
            f"{API_ROOT}/works",
            params=params,
            headers=api_headers(api_key),
            timeout=60,
        )
        if response.status_code == 429:
            LOG.warning("OpenAlex rate limit hit, sleeping 5s")
            time.sleep(5)
            continue
        response.raise_for_status()
        payload = response.json()
        works.extend(payload.get("results", []))
        cursor = (payload.get("meta") or {}).get("next_cursor")
    return works


def pmc_ids(work: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for value in (work.get("ids") or {}).values():
        match = re.search(r"/articles/(?:PMC)?(\d+)", str(value), re.IGNORECASE)
        if match:
            ids.append(f"PMC{match.group(1)}")
    for location in work.get("locations") or []:
        match = re.search(
            r"/articles/(?:PMC)?(\d+)",
            location.get("landing_page_url") or "",
            re.IGNORECASE,
        )
        if match:
            ids.append(f"PMC{match.group(1)}")
    return list(dict.fromkeys(ids))


def oa_pdf_urls(work: dict[str, Any]) -> list[str]:
    """Order candidate PDFs: published > OpenAlex content > other > preprint."""
    open_access = work.get("open_access") or {}
    if not open_access.get("is_oa"):
        return []

    primary_source = (work.get("primary_location") or {}).get("source") or {}
    primary_id = primary_source.get("id")
    buckets: list[list[str]] = [[], [], [], []]

    def add(location: dict[str, Any], published: bool) -> None:
        pdf_url = location.get("pdf_url")
        same_source = primary_id and (location.get("source") or {}).get("id") == primary_id
        if pdf_url:
            buckets[0 if published and same_source else 1 if published else 3].append(
                pdf_url
            )

    for location in work.get("locations") or []:
        if not location.get("is_oa"):
            continue
        add(location, location.get("version") == "publishedVersion")

    best = work.get("best_oa_location") or {}
    if best.get("is_oa") and best.get("version") == "publishedVersion":
        add(best, True)

    content_urls = work.get("content_urls") or {}
    if content_urls.get("pdf"):
        buckets[2].append(content_urls["pdf"])

    for pmcid in pmc_ids(work):
        buckets[1].append(f"https://europepmc.org/articles/{pmcid}?pdf=render")

    if open_access.get("oa_url"):
        buckets[3].append(open_access["oa_url"])

    seen: set[str] = set()
    ordered: list[str] = []
    for bucket in buckets:
        for url in bucket:
            if url not in seen:
                seen.add(url)
                ordered.append(url)
    return ordered


def fetch_pdf(url: str, timeout: int, api_key: str | None = None) -> bytes | None:
    headers = {"User-Agent": USER_AGENT}
    if api_key and url.startswith("https://content.openalex.org/"):
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = curl_requests.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
            headers=headers,
            stream=True,
        )
    except Exception as error:  # noqa: BLE001 - network failures are per-URL
        LOG.debug("PDF request failed %s: %s", url, error)
        return None

    try:
        if response.status_code != 200:
            LOG.debug("PDF HTTP %s for %s", response.status_code, url)
            return None
        blob = bytearray()
        for chunk in response.iter_content(65_536):
            blob.extend(chunk)
            if len(blob) > PDF_MAX_BYTES:
                LOG.debug("PDF too large for %s", url)
                return None
        if not is_pdf(bytes(blob)):
            LOG.debug("Not a PDF (%s bytes) at %s", len(blob), url)
            return None
        return bytes(blob)
    finally:
        response.close()


def source_name(work: dict[str, Any]) -> str:
    primary = (work.get("primary_location") or {}).get("source") or {}
    best = (work.get("best_oa_location") or {}).get("source") or {}
    name = primary.get("display_name") or best.get("display_name") or ""
    if not name:
        return ""
    return f"*{name.strip('*')}*"


def derive_tags(work: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for keyword in work.get("keywords") or []:
        label = keyword.get("display_name") or ""
        tag = "-".join(re.findall(r"[a-z0-9]+", ascii_fold(label).lower()))
        tag = tag[:60].strip("-")
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) == 3:
            break
    if not tags:
        topic = (work.get("primary_topic") or {}).get("subfield") or {}
        label = topic.get("display_name") or ""
        tag = "-".join(re.findall(r"[a-z0-9]+", ascii_fold(label).lower()))
        if tag:
            tags.append(tag)
    return tags


def build_entry(
    work: dict[str, Any],
    author_id: str,
    taken: set[str],
    author_name: str = DEFAULT_AUTHOR_NAME,
    timeout: int = 60,
    slug_override: str | None = None,
    max_authors: int = MAX_AUTHORS,
) -> Entry:
    year = int(work["publication_year"])
    title = clean_title(str(work["title"]))
    doi = normalize_doi(str(work.get("doi") or ""))
    slug = slug_override or unique_slug(slugify_title(year, title), taken)
    if slug_override:
        taken.add(slug_override)
    date = str(work.get("publication_date") or f"{year}-01-01")
    abstract = clean_abstract(reconstruct_abstract(work.get("abstract_inverted_index")))
    summary = summarize(abstract, title)
    pairs = author_pairs(work, author_id, author_name, timeout)
    if max_authors and len(pairs) > max_authors:
        head = pairs[:max_authors]
        if not any(is_me for _, is_me in head):
            head.append(next(pair for pair in pairs if pair[1]))
        pairs = [*head, ("et al.", False)]
    authors = [f"***{author_name}***" if is_me else name for name, is_me in pairs]
    citation_names = [author_name if is_me else name for name, is_me in pairs]
    journal = source_name(work)
    tags = derive_tags(work)
    citation = render_citation(
        citation_names,
        title,
        journal,
        work.get("biblio") or {},
        year,
    )
    pdf_urls = oa_pdf_urls(work)

    parsed_version = doi_version(doi)
    preprint_lines = []
    if work.get("type") == "preprint":
        preprint_lines.append("preprint = true")
        if parsed_version:
            preprint_lines.append(f"preprint_version = {parsed_version[1]}")
    lines = [
        "+++",
        "draft = false",
        "pin = false",
        'type = "publication"',
        *preprint_lines,
        f"summary = {toml_string(summary)}",
        'cover = ""',
        "",
        f"abstract = {toml_string(abstract)}",
        "",
        "authors = [" + ", ".join(toml_string(author) for author in authors) + "]",
        f"date = {toml_string(date)}",
    ]
    if journal:
        lines.append(f"journal = {toml_string(journal)}")
    lines.append(f"title = {toml_string(title)}")
    if tags:
        lines.append("tags = [" + ", ".join(toml_string(tag) for tag in tags) + "]")
    lines.append(f"doi = {toml_string(doi)}")
    lines.append(f"citation = {toml_string(citation)}")
    lines.append("+++")
    lines.append("")

    return Entry(
        slug=slug,
        doi=doi,
        title=title,
        front_matter="\n".join(lines),
        pdf_urls=pdf_urls,
    )


def write_pdf(
    entry: Entry,
    pdf_dir: Path,
    timeout: int,
    dry_run: bool = False,
    overwrite: bool = False,
    api_key: str | None = None,
) -> bool:
    target = pdf_dir / f"{entry.slug}.pdf"
    if target.exists() and not overwrite:
        LOG.info("PDF already present: %s", target)
        return True
    for url in entry.pdf_urls:
        blob = fetch_pdf(url, timeout, api_key)
        if blob is None:
            continue
        if not dry_run:
            target.write_bytes(blob)
            LOG.info("PDF saved: %s (%s bytes) from %s", target, len(blob), url)
        time.sleep(0.2)
        return True
    LOG.warning("No open-access PDF retrieved for %s", entry.doi)
    return False


@click.command()
@click.option(
    "--author",
    "author_profile",
    default=lambda: os.environ.get("OPENALEX_AUTHOR_PROFILE", DEFAULT_AUTHOR),
    show_default="OPENALEX_AUTHOR_PROFILE or A5004170724",
    help="OpenAlex author profile URL or ID.",
)
@click.option(
    "--api-key",
    default=lambda: os.environ.get("OPENALEX_API_KEY"),
    show_default="OPENALEX_API_KEY",
    help="OpenAlex API key.",
)
@click.option(
    "--author-name",
    default=lambda: os.environ.get("OPENALEX_AUTHOR_NAME", DEFAULT_AUTHOR_NAME),
    show_default="OPENALEX_AUTHOR_NAME or Robert A. Petit III",
    help="Name used for the profile author in bylines and citations.",
)
@click.option(
    "--types",
    default=DEFAULT_TYPES,
    show_default=True,
    help="Comma-separated OpenAlex work types.",
)
@click.option("--include-preprints/--no-preprints", default=False)
@click.option(
    "--include-abstracts/--no-abstracts",
    default=False,
    help="Include numbered conference poster abstracts.",
)
@click.option("--since-year", type=int, default=0, help="Ignore works older than this.")
@click.option("--max-new", type=int, default=0, help="Stop after N new entries (0 = all).")
@click.option(
    "--max-authors",
    type=int,
    default=MAX_AUTHORS,
    show_default=True,
    help="Authors shown before et al. (0 = all).",
)
@click.option("--content-dir", type=click.Path(path_type=Path), default=Path("content/publication"))
@click.option("--pdf-dir", type=click.Path(path_type=Path), default=Path("static/pdf"))
@click.option("--skip-pdfs/--with-pdfs", default=False)
@click.option("--apply/--dry-run", default=False)
@click.option("--report", type=click.Path(path_type=Path), help="Write a JSON report.")
@click.option("--timeout", type=int, default=60, help="Per-PDF request timeout in seconds.")
@click.option("--verbose", is_flag=True)
def main(
    author_profile: str,
    api_key: str | None,
    author_name: str,
    types: str,
    include_preprints: bool,
    include_abstracts: bool,
    since_year: int,
    max_new: int,
    max_authors: int,
    content_dir: Path,
    pdf_dir: Path,
    skip_pdfs: bool,
    apply: bool,
    report: Path | None,
    timeout: int,
    verbose: bool,
) -> None:
    """Create publication entries and OA PDFs that the site does not have yet."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if not api_key:
        LOG.warning("OPENALEX_API_KEY is unset; requests will be rate limited")

    content_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    author_id = author_id_from_profile(author_profile)
    allowed_types = [item.strip() for item in types.split(",") if item.strip()]
    if include_preprints and "preprint" not in allowed_types:
        allowed_types.append("preprint")

    existing = load_existing(content_dir, pdf_dir)
    taken = set(existing.slugs)
    seen_dois = set(existing.dois)
    seen_titles = set(existing.titles)
    seen_state: dict[str, tuple[bool, str, int]] = {}

    works = fetch_works(author_id, api_key, allowed_types)
    LOG.info("OpenAlex returned %s works for %s", len(works), author_id)
    works.sort(
        key=lambda work: (
            work.get("publication_date") or "",
            work.get("id") or "",
        ),
        reverse=True,
    )

    created: list[dict[str, str]] = []
    upgraded: list[dict[str, str]] = []
    skipped: dict[str, int] = {}
    pdf_failures: list[str] = []

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for work in works:
        if max_new and len(created) + len(upgraded) >= max_new:
            break
        title = str(work.get("title") or "").strip()
        doi = normalize_doi(str(work.get("doi") or ""))
        normalized_title = normalize_title(title)
        year = int(work.get("publication_year") or 0)

        if not doi:
            skip("missing-doi")
            continue
        if not title or not year:
            skip("missing-metadata")
            continue
        if work.get("is_retracted"):
            skip("retracted")
            continue
        if is_numbered_abstract(work) and not include_abstracts:
            skip("conference-abstract")
            continue
        if since_year and year < since_year:
            skip("too-old")
            continue
        if doi in seen_dois:
            skip("duplicate-doi")
            continue

        upgrade_path: Path | None = None
        if normalized_title in seen_titles:
            current = seen_state.get(normalized_title)
            if current is None:
                record = existing.by_title.get(normalized_title)
                if record is None:
                    skip("duplicate-title")
                    continue
                stored = doi_version(record.doi)
                current = (
                    record.preprint,
                    stored[0] if stored else "",
                    record.version,
                )
                seen_state[normalized_title] = current

            preprint, base, version = current
            is_upgrade = False
            if work.get("type") == "preprint":
                parsed = doi_version(doi)
                if (
                    preprint
                    and parsed
                    and base
                    and parsed[0] == base
                    and parsed[1] > version
                ):
                    is_upgrade = True
                    LOG.info(
                        "Upgrading preprint version %s to %s", version, parsed[1]
                    )
                    seen_state[normalized_title] = (True, base, parsed[1])
            elif preprint:
                is_upgrade = True
                seen_state[normalized_title] = (False, "", 0)
                LOG.info("Upgrading preprint to article")

            if not is_upgrade:
                skip("duplicate-title")
                continue
            record = existing.by_title.get(normalized_title)
            upgrade_path = record.path if record else None
            if upgrade_path is None:
                skip("duplicate-title")
                continue

        entry = build_entry(
            work,
            author_id,
            taken,
            author_name,
            timeout,
            slug_override=upgrade_path.stem if upgrade_path else None,
            max_authors=max_authors,
        )
        seen_dois.add(doi)
        seen_titles.add(normalized_title)
        candidate_version = doi_version(doi)
        seen_state[normalized_title] = (
            work.get("type") == "preprint",
            candidate_version[0] if candidate_version else "",
            candidate_version[1] if candidate_version else 0,
        )

        if "\npdf = " in entry.front_matter:
            raise AssertionError("pdf is appended after download")

        pdf_saved = False
        target_pdf = pdf_dir / f"{entry.slug}.pdf"
        if not skip_pdfs:
            if entry.pdf_urls:
                pdf_saved = write_pdf(
                    entry,
                    pdf_dir,
                    timeout,
                    dry_run=not apply,
                    overwrite=upgrade_path is not None,
                    api_key=api_key,
                )
            else:
                pdf_failures.append(doi)
        if apply and upgrade_path and not pdf_saved:
            target_pdf.unlink(missing_ok=True)

        if pdf_saved:
            entry.front_matter = entry.front_matter.replace(
                f'doi = {toml_string(doi)}',
                f'doi = {toml_string(doi)}\npdf = "/pdf/{entry.slug}.pdf"',
            )

        path = upgrade_path or (content_dir / f"{entry.slug}.md")
        action = "Updated" if upgrade_path else "Created"
        if apply:
            path.write_text(entry.front_matter, encoding="utf-8")
            LOG.info("%s %s", action, path)
        else:
            LOG.info("Would %s %s", action.lower(), path)

        record = {
            "slug": entry.slug,
            "doi": entry.doi,
            "title": entry.title,
            "pdf": "yes" if pdf_saved else "no",
        }
        (upgraded if upgrade_path else created).append(record)

    summary = {
        "author": author_id,
        "dry_run": not apply,
        "created": created,
        "upgraded": upgraded,
        "skipped": skipped,
        "pdf_followup": pdf_failures,
    }
    if report:
        report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    click.echo(
        f"{'Would create' if not apply else 'Created'} {len(created)} entries, "
        f"{'would update' if not apply else 'updated'} {len(upgraded)} preprints "
        f"({skipped.get('duplicate-doi', 0) + skipped.get('duplicate-title', 0)} duplicates skipped)"
    )
    for item in created:
        click.echo(f"  {item['slug']}  pdf={item['pdf']}")
    for item in upgraded:
        click.echo(f"  upgraded {item['slug']}  pdf={item['pdf']}")
    if pdf_failures:
        click.echo(f"{len(pdf_failures)} OA works had no downloadable PDF")


if __name__ == "__main__":
    sys.exit(main())