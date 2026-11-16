#!/usr/bin/env python3
"""Refresh data/github.json and data/merged.json from the GitHub GraphQL API.

Two searches: the author's 100 most recent pull requests outside their own
projects, and the merged count over the same filter. GitHub answers a search
with a 502 often enough that the first version of this job failed on one, so
every query retries 5xx and network errors; only a validated pair of responses
is written, which leaves the previous snapshot in place on a bad run.

`_meta` marks the files as generated without breaking the Hugo readers.
"""

import json
import logging
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

import rich_click as click

API = "https://api.github.com/graphql"
USER_AGENT = "robertpetit.com-pull-requests"
OUTPUT = Path("data")
FILTER = (
    "author:rpetit3 -user:rpetit3 -user:rpetit3-fun -user:staphopia"
    " -user:bactopia -user:Read-Lab-Confederation"
)
FIELDS = """
      number
      title
      repository {
        nameWithOwner
      }
      createdAt
      mergedAt
      url
      changedFiles
      additions
      deletions
"""
LATEST = f"""query {{
  search(query: "is:pr {FILTER}", type: ISSUE, first: 100) {{
    issueCount
    edges {{
      node {{
        ... on PullRequest {{{FIELDS}
        }}
      }}
    }}
  }}
}}"""
MERGED = f"""query {{
  search(query: "is:pr is:merged {FILTER}", type: ISSUE, first: 100) {{
    issueCount
  }}
}}"""
# Error types GitHub reports inside a 200; anything else is a real failure.
TRANSIENT = {"RATE_LIMITED", "INTERNAL", "SERVICE_UNAVAILABLE"}

log = logging.getLogger("pull-requests")


class FetchError(RuntimeError):
    pass


def post_json(payload: dict, token: str, timeout: int) -> tuple[int, dict]:
    """One GraphQL POST. Returns the status and the decoded body, even on error."""
    request = urllib.request.Request(
        API,
        data=json.dumps(payload).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            # A 502 from the edge is an HTML page, not JSON.
            return error.code, {"message": raw.decode(errors="replace")[:200]}


def graphql(
    query: str,
    token: str,
    timeout: int,
    attempts: int,
    poster=None,
) -> dict:
    """Run one query, retrying transient statuses with jittered backoff."""
    poster = poster or post_json
    for attempt in range(1, attempts + 1):
        try:
            status, body = poster({"query": query}, token, timeout)
        except (urllib.error.URLError, TimeoutError) as error:
            status, body = 0, {"message": str(error)}
        errors = body.get("errors") or []
        transient = status == 0 or status >= 500 or status == 429 or any(
            error.get("type") in TRANSIENT for error in errors
        )
        if status == 200 and body.get("data") and not errors:
            return body["data"]
        detail = body.get("message") or "; ".join(error.get("message", "") for error in errors)
        if not transient or attempt == attempts:
            raise FetchError(f"query failed after {attempt} attempt(s): HTTP {status}: {detail}")
        delay = 2 ** (attempt - 1) * (0.5 + random.random())
        log.warning("HTTP %s on attempt %d, retrying in %.1fs", status, attempt, delay)
        time.sleep(delay)
    raise FetchError("unreachable")


def checked(data: dict, *, edges: bool) -> dict:
    search = data.get("search")
    if not isinstance(search, dict) or not isinstance(search.get("issueCount"), int):
        raise FetchError(f"search result without an issueCount: {data!r:.200}")
    if edges:
        found = search.get("edges")
        if not isinstance(found, list):
            raise FetchError("search result without edges")
        for edge in found:
            node = edge.get("node") or {}
            if not node.get("repository") or not node.get("url"):
                raise FetchError(f"edge without repository or url: {edge!r:.200}")
    return search


def write(name: str, payload: dict) -> None:
    target = OUTPUT / f"{name}.json"
    scratch = target.with_suffix(".json.tmp")
    scratch.write_text(json.dumps({"_meta": {"generated_by": "query_pull_requests.py"}, **payload}, indent=2) + "\n")
    os.replace(scratch, target)
    log.info("wrote %s", target)


@click.command()
@click.option("--timeout", default=30, show_default=True, help="Seconds per request")
@click.option("--attempts", default=5, show_default=True, help="Tries per query")
def main(timeout: int, attempts: int) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise FetchError("GITHUB_TOKEN or GH_TOKEN is required")
    latest = checked(graphql(LATEST, token, timeout, attempts), edges=True)
    merged = checked(graphql(MERGED, token, timeout, attempts), edges=False)
    write("github", {"search": latest})
    write("merged", {"search": merged})


if __name__ == "__main__":
    try:
        main()
    except FetchError as error:
        log.error("%s", error)
        raise SystemExit(1)