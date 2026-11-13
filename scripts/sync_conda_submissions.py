#!/usr/bin/env python3
"""Rebuild the conda submissions in data/volunteer.yml from public sources.

Three sources feed the list: merged pull requests by AUTHOR that add a recipe to
bioconda-recipes or conda-forge/staged-recipes, and packages on the personal
anaconda.org channel. A source that fails keeps its previous entries and is
named under _meta.incomplete, so a partial run never silently drops history.
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

API_ROOT = "https://api.github.com"
ANACONDA_ROOT = "https://api.anaconda.org"
CHANNEL_ROOT = "https://conda.anaconda.org"
USER_AGENT = "robertpetit.com-conda-submissions"
DEFAULT_AUTHOR = "rpetit3"
RECIPE_FILE = re.compile(r"^recipes/([^/]+)/meta\.yaml$")
PLAIN_SCALAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/()+@%&*-]*$")
JINJA = re.compile(r"\{\{\s*name\s*\}\}")
BLOCK = re.compile(r"^  (home|summary): (.*)$")
# Recipes the author wrote but somebody else opened the pull request for, so a
# search by author cannot find them.
EXTRA_PRS = ("https://github.com/bioconda/bioconda-recipes/pull/32810",)
SOURCES = {
    "bioconda": "bioconda/bioconda-recipes",
    "staged": "conda-forge/staged-recipes",
}
LABELS = {"bioconda": "Bioconda", "staged": "Conda-Forge"}
# Pulls each source's entries back out of an existing rendered file.
PREFIXES = {
    "bioconda": "https://github.com/bioconda/bioconda-recipes/pull/",
    "staged": "https://github.com/conda-forge/staged-recipes/pull/",
    "channel": "https://anaconda.org/",
}


class SyncError(RuntimeError):
    pass


def fetch(url: str, timeout: int, accept: str = "application/vnd.github+json") -> bytes:
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith(API_ROOT):
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def api(path: str, timeout: int) -> object:
    return json.loads(fetch(f"{API_ROOT}{path}", timeout))


def source_of(url: str) -> str | None:
    for key, prefix in PREFIXES.items():
        if url.startswith(prefix):
            return key
    return None


def merged_prs(repo: str, author: str, timeout: int) -> list[dict]:
    """Every merged PR by author, newest first."""
    query = urllib.parse.quote(f"repo:{repo} is:pr author:{author} is:merged")
    found: list[dict] = []
    for page in range(1, 11):
        batch = api(f"/search/issues?q={query}&per_page=100&page={page}&sort=created", timeout)
        found.extend(batch["items"])
        if len(batch["items"]) < 100:
            break
    return found


def added_recipes(repo: str, number: int, timeout: int) -> list[str]:
    """Recipe directory names this PR creates, ignoring edited existing recipes."""
    files: list[dict] = []
    for page in range(1, 11):
        batch = api(f"/repos/{repo}/pulls/{number}/files?per_page=100&page={page}", timeout)
        files.extend(batch)
        if len(batch) < 100:
            break
    names = []
    for item in files:
        match = RECIPE_FILE.match(item["filename"])
        if match and item["status"] == "added":
            names.append(match.group(1))
    return sorted(set(names))


def about(recipe: str, repo: str, sha: str, timeout: int) -> tuple[str, str]:
    """(home, summary) from a recipe's about block; Jinja names resolved."""
    raw = fetch(f"{API_ROOT}/repos/{repo}/contents/recipes/{recipe}/meta.yaml?ref={sha}", timeout)
    document = json.loads(raw)
    if "content" not in document:
        raise SyncError(f"{repo}: recipes/{recipe}/meta.yaml has no inline content")
    lines = base64.b64decode(document["content"]).decode("utf-8", "replace").splitlines()
    block: dict[str, str] = {}
    inside = False
    for line in lines:
        if line.rstrip() == "about:":
            inside = True
            continue
        if inside:
            if not line.startswith(" "):
                break
            match = BLOCK.match(line)
            if match:
                block[match.group(1)] = yaml.safe_load(match.group(2)) or ""
    return (
        JINJA.sub(recipe, str(block.get("home", "") or "")).strip(),
        " ".join(str(block.get("summary", "") or "").split()),
    )


def display_name(recipe: str, title: str) -> str:
    """Recipe name in the casing the pull request title used, else the package name."""
    wanted = re.sub(r"[^a-z0-9]", "", recipe.lower())
    for token in title.split():
        if re.sub(r"[^a-z0-9]", "", token.lower()) == wanted:
            return token.strip("`'\"")
    return recipe


def pr_entries(key: str, author: str, timeout: int, limit: int) -> list[dict]:
    repo = SOURCES[key]
    found = []
    for pr in merged_prs(repo, author, timeout)[:limit]:
        recipes = added_recipes(repo, pr["number"], timeout)
        if not recipes:
            continue
        detail = api(f"/repos/{repo}/pulls/{pr['number']}", timeout)
        for recipe in recipes:
            home, summary = about(recipe, repo, detail["head"]["sha"], timeout)
            tool = display_name(recipe, detail["title"])
            url = f"{PREFIXES[key]}{pr['number']}"
            found.append(
                {
                    "title": f"Submitted {tool} to {LABELS[key]}",
                    "date": (detail.get("merged_at") or pr["created_at"])[:10],
                    "pr_url": url,
                    "pr_name": f"{repo}#{pr['number']}",
                    "tool": tool,
                    # an empty about.home would self-link, so fall back to the PR
                    "tool_url": home or url,
                    "description": summary,
                }
            )
    return found


def channel_names(user: str, timeout: int) -> list[str]:
    names = set()
    for subdir in ("linux-64", "noarch"):
        try:
            data = json.loads(fetch(f"{CHANNEL_ROOT}/{user}/{subdir}/repodata.json", timeout))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        names.update(info["name"] for info in data.get("packages", {}).values())
        names.update(info["name"] for info in data.get("packages.conda", {}).values())
    return sorted(names)


def channel_entries(user: str, timeout: int) -> list[dict]:
    found = []
    for name in channel_names(user, timeout):
        package = json.loads(fetch(f"{ANACONDA_ROOT}/package/{user}/{name}", timeout))
        uploads = [item["upload_time"] for item in package.get("files", []) if item.get("upload_time")]
        url = f"https://anaconda.org/{user}/{name}"
        found.append(
            {
                "title": f"Submitted {name} to personal Anaconda channel",
                "date": min(uploads)[:10] if uploads else "",
                "pr_url": url,
                "pr_name": f"anaconda/{user}",
                "tool": name,
                # an empty home would self-link, so fall back to the package page
                "tool_url": package.get("home") or url,
                "description": package.get("summary") or "",
            }
        )
    return found


def drop_shadowed(channel: list[dict], recipes: list[dict]) -> list[dict]:
    """Channel packages already listed from a recipe repo: the PR is the better link."""
    shadowed = {row["tool"].lower().replace("_", "-") for row in recipes}
    return [row for row in channel if row["tool"].lower().replace("_", "-") not in shadowed]


def previous_entries(path: Path) -> list[dict]:
    """Rows already in the file, with YAML dates and scalars forced to strings."""
    if not path.exists():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = []
    for row in document.get("conda") or []:
        rows.append({name: "" if value is None else str(value) for name, value in row.items()})
    return rows


def key(row: dict) -> tuple[str, str]:
    """One row per (pull request, recipe); a PR can add several recipes."""
    return row["pr_url"], row.get("tool", "")


def merge(previous: list[dict], fetched: dict[str, list[dict]], failed: set[str]) -> list[dict]:
    """Fetched entries win; a failed source keeps its old rows, unknown URLs stay."""
    kept: dict[tuple[str, str], dict] = {}
    for row in previous:
        if row.get("pr_url") in EXTRA_PRS:
            kept.setdefault(key(row), row)
    for row in previous:
        if source_of(row.get("pr_url", "")) in failed:
            kept[key(row)] = row
    for rows in fetched.values():
        for row in rows:
            kept[key(row)] = row
    for row in previous:
        if source_of(row.get("pr_url", "")) is None:
            kept.setdefault(key(row), row)
    rows = sorted(kept.values(), key=lambda row: row["tool"].lower())
    return sorted(rows, key=lambda row: row.get("date") or "", reverse=True)


def scalar(value: str) -> str:
    value = str(value)
    if PLAIN_SCALAR.match(value):
        return value
    return json.dumps(value)


def render(rows: list[dict], as_of: str, failed: set[str]) -> str:
    lines = [
        "# generated by scripts/sync_conda_submissions.py; do not edit",
        "_meta:",
        f'  as_of: "{as_of}"',
    ]
    if failed:
        lines.append("  incomplete:")
        lines.extend(f"    - {kind}" for kind in sorted(failed))
    if not rows:
        lines.append("conda: []")
        return "\n".join(lines) + "\n"
    lines.append("conda:")
    for row in rows:
        lines.append(f"  - title: {scalar(row['title'])}")
        lines.append(f"    date: {scalar(row.get('date') or '')}")
        lines.append(f"    pr_url: {scalar(row['pr_url'])}")
        lines.append(f"    pr_name: {scalar(row['pr_name'])}")
        lines.append(f"    tool: {scalar(row['tool'])}")
        lines.append(f"    tool_url: {scalar(row.get('tool_url') or '')}")
        lines.append(f"    description: {scalar(row.get('description') or '')}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", default=DEFAULT_AUTHOR)
    parser.add_argument("--out", type=Path, default=Path("data/volunteer.yml"))
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--limit", type=int, default=500, help="max PRs per source")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    previous = previous_entries(args.out)
    fetched: dict[str, list[dict]] = {}
    failed: set[str] = set()
    for kind in SOURCES:
        try:
            fetched[kind] = pr_entries(kind, args.author, args.timeout, args.limit)
        except (urllib.error.URLError, SyncError, KeyError, ValueError, OSError) as error:
            print(f"warning: {kind} failed: {error}", file=sys.stderr)
            failed.add(kind)
    try:
        fetched["channel"] = channel_entries(args.author, args.timeout)
    except (urllib.error.URLError, SyncError, KeyError, ValueError, OSError) as error:
        print(f"warning: channel failed: {error}", file=sys.stderr)
        failed.add("channel")

    recipes = [row for kind in SOURCES for row in fetched.get(kind, [])]
    fetched["channel"] = drop_shadowed(fetched.get("channel", []), recipes)
    rows = merge(previous, fetched, failed)
    text = render(rows, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), failed)
    if args.dry_run:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: {len(rows)} entries, failed sources: {sorted(failed) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())