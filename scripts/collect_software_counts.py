#!/usr/bin/env python3
"""Write data/software_counts.yml from a boast snapshot of the site's tools.

Tool metadata lives in each content/software/*.md page: the repository is taken
from `repo` (or a github.com `link`), the Bioconda package from the page title
when `conda` is true, and an optional `paper_doi` adds citation counts. Only
public repositories under ALLOWED_OWNERS are allowed, so a page can never leak
a private repository into the rendered counts.

Stars and downloads come from a boast snapshot; citation counts are read from
data/citations-count.yml, which scripts/sync_publications.py writes weekly.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

ALLOWED_OWNERS = {"rpetit3", "bactopia", "staphopia"}
EXCLUDE_FILE = Path("scripts/software_exclude.txt")
GITHUB_REPO = re.compile(r"github\.com/([^/#?]+)/([^/#?\s]+)")
SNAPSHOT_WRITTEN = re.compile(r"Snapshot written to (.+)$", re.MULTILINE)
USER_AGENT = "robertpetit.com-software-counts"
# Snapshot layout this parser reads. Bump deliberately when boast changes it.
SUPPORTED_SCHEMA = {3}


class CollectError(RuntimeError):
    pass


def front_matter(path: Path) -> dict | None:
    """Parse the YAML front matter block of a page; None for pages without one."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return None
    for end, line in enumerate(lines[1:], start=1):
        if line == "---":
            return yaml.safe_load("\n".join(lines[1:end])) or {}
    raise CollectError(f"{path}: unterminated front matter")


def tool_identity(name: str, repo: str | None, link: str | None) -> str:
    if not repo:
        match = GITHUB_REPO.search(link or "")
        if match:
            repo = f"{match.group(1)}/{match.group(2)}"
    if not repo:
        raise CollectError(f"{name}: no `repo` and no github.com `link`")
    owner = repo.split("/")[0]
    if owner not in ALLOWED_OWNERS:
        raise CollectError(
            f"{name}: {repo} is under '{owner}', not one of {sorted(ALLOWED_OWNERS)}"
        )
    return f"github:{repo}"


def projects(content_dir: Path) -> list[dict]:
    """One entry per software page with its boast identities and paper DOI."""
    found = []
    for page in sorted(content_dir.glob("*.md")):
        meta = front_matter(page)
        if meta is None or "software_pin" not in meta:
            continue
        title = meta["title"]
        identities = [tool_identity(title, meta.get("repo"), meta.get("link"))]
        if meta.get("conda"):
            identities.append(f"conda:bioconda/{title}")
        found.append({"title": title, "identities": identities, "doi": meta.get("paper_doi")})

    if not found:
        raise CollectError(f"{content_dir}: no software pages found")
    titles = [project["title"] for project in found]
    duplicates = sorted({title for title in titles if titles.count(title) > 1})
    if duplicates:
        raise CollectError(f"duplicate software titles: {duplicates}")
    identities = [identity for project in found for identity in project["identities"]]
    duplicates = sorted({i for i in identities if identities.count(i) > 1})
    if duplicates:
        raise CollectError(f"identities listed by more than one page: {duplicates}")
    return found


def public_repos(owner: str, timeout: int) -> set[str]:
    request = urllib.request.Request(
        f"https://api.github.com/users/{owner}/repos?per_page=100&type=public",
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return {
            f"{owner}/{repo['name']}"
            for repo in json.load(response)
            if not repo["fork"]
        }


def has_history(repo: str, timeout: int) -> bool:
    """False for placeholder repos holding nothing but an initial commit."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/commits?per_page=2",
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return len(json.load(response)) > 1


def excluded_repos(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def report_unlisted(tracked: set[str], exclude: set[str], timeout: int) -> None:
    """Warn about public repos that look like real tools but have no page."""
    listed = {identity.removeprefix("github:") for identity in tracked}
    for owner in sorted(ALLOWED_OWNERS):
        try:
            repos = public_repos(owner, timeout)
        except OSError as error:
            print(f"warning: could not list {owner} repos: {error}", file=sys.stderr)
            continue
        unlisted = []
        for repo in sorted(repos - listed - exclude):
            try:
                if has_history(repo, timeout):
                    unlisted.append(repo)
            except OSError as error:
                print(f"warning: could not read {repo} commits: {error}", file=sys.stderr)
        if unlisted:
            print("warning: public repos with no software page:", file=sys.stderr)
            for repo in unlisted:
                print(f"  {repo}", file=sys.stderr)


def write_manifest(projects_: list[dict], path: Path) -> None:
    """One Project holding every identity, so a run writes a single snapshot."""
    lines = ["# generated by scripts/collect_software_counts.py", "[[project]]", "identities = ["]
    for project in projects_:
        lines += [f'    "{identity}",' for identity in project["identities"]]
    lines += ["]", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_boast(manifest: Path, snapshot_dir: Path, boast: str, timeout: int) -> Path:
    """Run boast and return the path of the snapshot it wrote."""
    try:
        result = subprocess.run(
            [boast, "about", str(manifest), "--snapshot-dir", str(snapshot_dir), "--quiet"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise CollectError(f"{boast}: not installed") from error
    except subprocess.TimeoutExpired as error:
        raise CollectError(f"{boast}: timed out after {timeout}s") from error

    # Exit 1 means at least one Provider failed; that partial snapshot is still
    # written and is the honest result.
    if result.returncode not in (0, 1):
        raise CollectError(f"{boast} exited {result.returncode}:\n{result.stderr.strip()}")
    match = SNAPSHOT_WRITTEN.search(result.stdout + result.stderr)
    if not match:
        raise CollectError(f"{boast} wrote no snapshot:\n{result.stderr.strip()}")
    if result.returncode == 1:
        print(f"boast reported failed providers; writing partial counts:\n{result.stderr.strip()}")
    return Path(match.group(1).strip())


def citation_counts(path: Path) -> dict[str, int]:
    """Cited-by counts keyed by lower-case DOI, as written by the sync script."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data.pop("_meta", None)
    return {str(doi).lower(): int(count) for doi, count in data.items()}


def _rendered(result: dict) -> bool:
    """Only failures that cost a rendered number mark a tool incomplete.

    OpenAlex and Europe PMC also search for repo mentions, which are not shown;
    their rate limits must not flag a tool whose stars and downloads were both
    retrieved.
    """
    return result["category"] in {"code", "downloads"}


def extract(snapshot: dict, projects_: list[dict], counts: dict[str, int | None]) -> dict[str, dict]:
    schema = snapshot.get("schema_version")
    if schema not in SUPPORTED_SCHEMA:
        raise CollectError(
            f"unsupported boast snapshot schema {schema}; update SUPPORTED_SCHEMA"
        )
    by_identity: dict[str, list[dict]] = {}
    for result in snapshot["results"]:
        by_identity.setdefault(result["identity"], []).append(result)

    rows: dict[str, dict] = {}
    for project in projects_:
        row: dict = {}
        incomplete = False
        for identity in project["identities"]:
            results = by_identity.get(identity, [])
            if not results:
                raise CollectError(f"{identity}: absent from snapshot")
            for result in results:
                outcome = result["outcome"]
                if outcome["status"] == "failed" and _rendered(result):
                    incomplete = True
                if outcome["status"] != "values":
                    continue
                for metric in outcome["metrics"]:
                    if metric["name"] not in {"stars", "downloads"}:
                        continue
                    row[metric["name"]] = metric["value"]["value"]
        if project["doi"]:
            found = counts.get(project["doi"].lower())
            if found is None:
                incomplete = True
            else:
                row["citations"] = found
        if incomplete:
            row["incomplete"] = True
        rows[project["title"].replace("-", "_")] = row
    return rows


def render_yaml(rows: dict[str, dict], as_of: str) -> str:
    lines = [
        "# generated by scripts/collect_software_counts.py; do not edit",
        "_meta:",
        f'  as_of: "{as_of}"',
    ]
    for key in sorted(rows):
        lines.append(f"{key}:")
        # downloads first, then alphabetical; every entry is a one-element list
        # to match the templates' `index . 0`.
        ordered = sorted(rows[key].items(), key=lambda item: item[0] != "downloads")
        for position, (name, value) in enumerate(ordered):
            lines.append(f"{'  - ' if position == 0 else '    '}{name}: {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def prune(snapshot_dir: Path, keep: int, current: Path) -> None:
    snapshots = sorted(path for path in snapshot_dir.glob("*.json") if path != current)
    for stale in snapshots[:-keep] if keep else snapshots:
        stale.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-dir", type=Path, default=Path("content/software"))
    parser.add_argument("--out", type=Path, default=Path("data/software-counts.yml"))
    parser.add_argument("--citations", type=Path, default=Path("data/citations-count.yml"))
    parser.add_argument("--snapshot-dir", type=Path, default=Path("metrics/snapshots"))
    parser.add_argument("--manifest", type=Path, default=Path("metrics/manifest.toml"))
    parser.add_argument("--from-snapshot", type=Path, help="re-render an existing snapshot")
    parser.add_argument("--keep-snapshots", type=int, default=26)
    parser.add_argument("--boast", default="boast")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--no-discover", action="store_true")
    parser.add_argument("--exclude-file", type=Path, default=EXCLUDE_FILE)
    args = parser.parse_args()

    try:
        projects_ = projects(args.content_dir)
        if not args.no_discover:
            report_unlisted(
                {i for project in projects_ for i in project["identities"]},
                excluded_repos(args.exclude_file),
                30,
            )
        if args.from_snapshot:
            snapshot_path = args.from_snapshot
        else:
            write_manifest(projects_, args.manifest)
            snapshot_path = run_boast(args.manifest, args.snapshot_dir, args.boast, args.timeout)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        counts = citation_counts(args.citations) if args.citations.exists() else {}
        args.out.write_text(
            render_yaml(extract(snapshot, projects_, counts), snapshot["created_at"]),
            encoding="utf-8",
        )
        if not args.from_snapshot:
            prune(args.snapshot_dir, args.keep_snapshots, snapshot_path)
    except CollectError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"wrote {args.out} from {snapshot_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())