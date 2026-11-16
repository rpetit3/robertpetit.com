"""Guards for scripts/query_pull_requests.py: retries, validation, atomic writes.

GitHub answers a GraphQL search with a 502 often enough that the job failed on
one, so a transient status has to be retried while a real error has to stop.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

SCRIPT = Path(__file__).parents[1] / "scripts" / "query_pull_requests.py"


@pytest.fixture(scope="module")
def qpr():
    spec = importlib.util.spec_from_file_location("query_pull_requests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

NODE = {
    "number": 1,
    "title": "add a thing",
    "repository": {"nameWithOwner": "someone/project"},
    "createdAt": "2026-01-01T00:00:00Z",
    "mergedAt": None,
    "url": "https://github.com/someone/project/pull/1",
    "changedFiles": 1,
    "additions": 1,
    "deletions": 0,
}


def response(*, edges: bool = True) -> tuple[int, dict]:
    search: dict = {"issueCount": 1}
    if edges:
        search["edges"] = [{"node": NODE}]
    return 200, {"data": {"search": search}}


def scripted(steps: list[tuple[int, dict]]):
    """Poster that replays steps, then repeats the last one."""
    remaining = list(steps)
    seen: list[str] = []

    def post(payload: dict, token: str, timeout: int) -> tuple[int, dict]:
        seen.append(payload["query"])
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    post.seen = seen  # type: ignore[attr-defined]
    return post


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch, qpr) -> None:
    monkeypatch.setattr(qpr.time, "sleep", lambda _seconds: None)


def test_queries_keep_the_filter_and_search_type(qpr) -> None:
    for query in (qpr.LATEST, qpr.MERGED):
        assert "type: ISSUE" in query
        for handle in ("rpetit3-fun", "staphopia", "bactopia", "Read-Lab-Confederation"):
            assert f"-user:{handle}" in query
    assert "is:merged" in qpr.MERGED
    assert "is:merged" not in qpr.LATEST


def test_502_is_retried(qpr, monkeypatch: pytest.MonkeyPatch) -> None:
    post = scripted([(502, {"message": "Bad Gateway"}), response()])
    monkeypatch.setattr(qpr, "post_json", post)
    assert qpr.graphql(qpr.LATEST, "t", 5, 3)["search"]["issueCount"] == 1
    assert len(post.seen) == 2


def test_network_error_is_retried(qpr, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def post(payload: dict, token: str, timeout: int) -> tuple[int, dict]:
        calls["n"] += 1
        if calls["n"] < 3:
            raise qpr.urllib.error.URLError("connection reset")
        return response()

    monkeypatch.setattr(qpr, "post_json", post)
    assert qpr.graphql(qpr.MERGED, "t", 5, 3)["search"]["issueCount"] == 1
    assert calls["n"] == 3


def test_transient_graphql_error_is_retried(qpr, monkeypatch: pytest.MonkeyPatch) -> None:
    post = scripted([(200, {"errors": [{"type": "RATE_LIMITED", "message": "slow down"}]}), response()])
    monkeypatch.setattr(qpr, "post_json", post)
    assert qpr.graphql(qpr.LATEST, "t", 5, 3)["search"]["edges"]
    assert len(post.seen) == 2


def test_permanent_graphql_error_stops_at_once(qpr, monkeypatch: pytest.MonkeyPatch) -> None:
    post = scripted([(200, {"errors": [{"type": "NOT_FOUND", "message": "nope"}]})])
    monkeypatch.setattr(qpr, "post_json", post)
    with pytest.raises(qpr.FetchError, match="NOT_FOUND|nope"):
        qpr.graphql(qpr.LATEST, "t", 5, 3)
    assert len(post.seen) == 1


def test_gives_up_after_the_attempt_budget(qpr, monkeypatch: pytest.MonkeyPatch) -> None:
    post = scripted([(502, {"message": "Bad Gateway"})])
    monkeypatch.setattr(qpr, "post_json", post)
    with pytest.raises(qpr.FetchError, match="3 attempt"):
        qpr.graphql(qpr.LATEST, "t", 5, 3)
    assert len(post.seen) == 3


def test_edges_are_validated(qpr) -> None:
    with pytest.raises(qpr.FetchError, match="edges"):
        qpr.checked({"search": {"issueCount": 2}}, edges=True)
    with pytest.raises(qpr.FetchError, match="url"):
        qpr.checked({"search": {"issueCount": 1, "edges": [{"node": {"repository": {}}}]}}, edges=True)
    with pytest.raises(qpr.FetchError, match="issueCount"):
        qpr.checked({"search": {"edges": []}}, edges=True)


def run(qpr, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, post) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(qpr, "post_json", post)
    monkeypatch.setenv("GITHUB_TOKEN", "token")


def test_both_files_are_written_with_meta(qpr, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run(qpr, tmp_path, monkeypatch, scripted([response(), response(edges=False)]))
    result = CliRunner().invoke(qpr.main, [])
    assert result.exit_code == 0, result.output
    github = json.loads((tmp_path / "data" / "github.json").read_text())
    merged = json.loads((tmp_path / "data" / "merged.json").read_text())
    assert github["_meta"]["generated_by"] == "query_pull_requests.py"
    assert github["search"]["edges"][0]["node"]["url"] == NODE["url"]
    assert merged["search"]["issueCount"] == 1
    assert not list((tmp_path / "data").glob("*.tmp"))


def test_a_failed_query_keeps_the_previous_snapshot(qpr, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run(qpr, tmp_path, monkeypatch, scripted([response(), (502, {"message": "Bad Gateway"})]))
    stale = tmp_path / "data" / "merged.json"
    stale.write_text('{"search": {"issueCount": 41}}')
    result = CliRunner().invoke(qpr.main, [])
    assert result.exit_code == 1
    assert json.loads(stale.read_text())["search"]["issueCount"] == 41
    assert not (tmp_path / "data" / "github.json").exists()


def test_missing_token_is_reported(qpr, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(qpr.FetchError, match="TOKEN"):
        qpr.main.callback(30, 5)