"""Tests for scripts/collect_software_counts.py."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[1] / "scripts" / "collect_software_counts.py"


@pytest.fixture(scope="module")
def collector():
    spec = importlib.util.spec_from_file_location("collect_software_counts", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page(directory: Path, name: str, body: str) -> Path:
    path = directory / f"{name}.md"
    path.write_text(f"---\n{body}\n---\n", encoding="utf-8")
    return path


def snapshot(results: list[dict]) -> dict:
    return {"schema_version": 3, "created_at": "2026-11-13T00:00:00Z", "results": results}


def values(identity: str, provider: str, name: str, value: int) -> dict:
    return {
        "provider": provider,
        "identity": identity,
        "category": "code",
        "outcome": {
            "status": "values",
            "metrics": [{"name": name, "provider": provider, "value": {"type": "count", "value": value}}],
        },
    }


def failed(identity: str, provider: str = "github", category: str = "code") -> dict:
    return {"provider": provider, "identity": identity, "category": category, "outcome": {"status": "failed"}}


def test_projects_build_identity_list(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"\nconda: true')
    page(tmp_path, "beta", 'title: "beta"\nsoftware_pin: false\nrepo: "bactopia/beta"\npaper_doi: "10.1/x"\nconda: false')
    page(tmp_path, "notes", 'title: "notes"')

    assert collector.projects(tmp_path) == [
        {"title": "alpha", "identities": ["github:rpetit3/alpha", "conda:bioconda/alpha"], "doi": None},
        {"title": "beta", "identities": ["github:bactopia/beta"], "doi": "10.1/x"},
    ]


def test_private_owner_rejected(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/someone/secret"')
    with pytest.raises(collector.CollectError, match="someone"):
        collector.projects(tmp_path)


def test_page_without_repo_rejected(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://example.org/alpha"')
    with pytest.raises(collector.CollectError, match="no `repo`"):
        collector.projects(tmp_path)


def test_missing_identity_rejected(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"')
    with pytest.raises(collector.CollectError, match="absent from snapshot"):
        collector.extract(snapshot([]), collector.projects(tmp_path), {})


def test_extract_collects_rendered_metrics_and_flags_failures(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"\nconda: true')
    page(tmp_path, "beta", 'title: "beta"\nsoftware_pin: false\nrepo: "bactopia/beta"\npaper_doi: "10.1/x"')
    results = [
        values("github:rpetit3/alpha", "github", "stars", 7),
        values("conda:bioconda/alpha", "anaconda", "downloads", 100),
        failed("github:bactopia/beta"),
        values("github:bactopia/beta", "openalex", "mentions", 40),
    ]

    rows = collector.extract(snapshot(results), collector.projects(tmp_path), {"10.1/x": 12})

    assert rows["alpha"] == {"stars": 7, "downloads": 100}
    assert rows["beta"] == {"citations": 12, "incomplete": True}


def test_unrendered_mention_failure_keeps_row_complete(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"')
    results = [
        values("github:rpetit3/alpha", "github", "stars", 7),
        failed("github:rpetit3/alpha", provider="openalex", category="citations"),
    ]

    assert collector.extract(snapshot(results), collector.projects(tmp_path), {})["alpha"] == {"stars": 7}


def test_citation_counts_reads_dois(collector, tmp_path):
    data = tmp_path / "citations-count.yml"
    data.write_text('_meta:\n  as_of: "2026-11-13T00:00:00Z"\n"10.1/X": 9\n', encoding="utf-8")

    assert collector.citation_counts(data) == {"10.1/x": 9}


def test_failed_citation_lookup_marks_incomplete(collector, tmp_path):
    page(tmp_path, "beta", 'title: "beta"\nsoftware_pin: false\nrepo: "bactopia/beta"\npaper_doi: "10.1/x"')
    results = [values("github:bactopia/beta", "github", "stars", 7)]

    rows = collector.extract(snapshot(results), collector.projects(tmp_path), {"10.1/x": None})

    assert rows["beta"] == {"stars": 7, "incomplete": True}


def test_duplicate_identity_rejected(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"')
    page(tmp_path, "beta", 'title: "beta"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"')
    with pytest.raises(collector.CollectError, match="more than one page"):
        collector.projects(tmp_path)


def test_unknown_schema_rejected(collector, tmp_path):
    page(tmp_path, "alpha", 'title: "alpha"\nsoftware_pin: false\nlink: "https://github.com/rpetit3/alpha"')
    with pytest.raises(collector.CollectError, match="schema"):
        collector.extract({"schema_version": 99, "results": []}, collector.projects(tmp_path), {})


def test_render_yaml_is_valid_and_list_shaped(collector):
    rendered = collector.render_yaml({"alpha": {"downloads": 100, "stars": 7}}, "2026-11-13T00:00:00Z")
    parsed = yaml.safe_load(rendered)

    assert parsed["_meta"]["as_of"] == "2026-11-13T00:00:00Z"
    assert parsed["alpha"] == [{"downloads": 100, "stars": 7}]
    assert json.loads(json.dumps("2026-11-13T00:00:00Z")) == "2026-11-13T00:00:00Z"


def test_excluded_repos_ignores_comments(collector, tmp_path):
    exclude = tmp_path / "exclude.txt"
    exclude.write_text("# comment\n\na/b\n", encoding="utf-8")
    assert collector.excluded_repos(exclude) == {"a/b"}