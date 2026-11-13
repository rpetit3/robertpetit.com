"""Tests for scripts/sync_conda_submissions.py."""

import base64
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "sync_conda_submissions.py"


@pytest.fixture(scope="module")
def sync():
    spec = importlib.util.spec_from_file_location("sync_conda_submissions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(url: str, tool: str = "tool", date: str = "2022-01-01") -> dict:
    return {
        "title": f"Submitted {tool} to Bioconda",
        "date": date,
        "pr_url": url,
        "pr_name": "bioconda/bioconda-recipes#1",
        "tool": tool,
        "tool_url": "https://example.org",
        "description": "d",
    }


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/bioconda/bioconda-recipes/pull/12", "bioconda"),
        ("https://github.com/conda-forge/staged-recipes/pull/12", "staged"),
        ("https://anaconda.org/rpetit3/aspera-connect", "channel"),
        ("https://bitbucket.org/x/y", None),
    ],
)
def test_source_of(sync, url, expected):
    assert sync.source_of(url) == expected


def test_added_recipes_ignores_edits_and_noise(sync, monkeypatch):
    files = [
        {"filename": "recipes/pasty/meta.yaml", "status": "added"},
        {"filename": "recipes/pasty/build.sh", "status": "added"},
        {"filename": "recipes/pasty/old.patch", "status": "removed"},
        {"filename": "recipes/existing/meta.yaml", "status": "modified"},
        {"filename": "recipes/other/meta.yaml", "status": "added"},
        {"filename": "recipes/other/skip-recipes/meta.yaml", "status": "added"},
    ]
    monkeypatch.setattr(sync, "api", lambda path, timeout: files)
    assert sync.added_recipes("bioconda/bioconda-recipes", 1, 5) == ["other", "pasty"]


def test_added_recipes_pages(sync, monkeypatch):
    pages = {
        1: [{"filename": f"recipes/r{n}/meta.yaml", "status": "added"} for n in range(30)],
        2: [{"filename": "recipes/late/meta.yaml", "status": "added"}],
    }
    seen = []

    def fake_api(path, timeout):
        page = int(path.rsplit("page=", 1)[1])
        seen.append(page)
        return pages[page]

    monkeypatch.setattr(sync, "api", fake_api)
    # A short page ends the walk; pad the first page to 100 so page 2 is read.
    pages[1] = [{"filename": f"recipes/r{n}/meta.yaml", "status": "added"} for n in range(100)]
    expected = sorted(["late"] + [f"r{n}" for n in range(100)])
    assert sync.added_recipes("bioconda/bioconda-recipes", 1, 5) == expected
    assert seen == [1, 2]


def test_about_reads_home_and_summary(sync, monkeypatch):
    meta = (
        "{% set version = '1.0' %}\n"
        "package:\n  name: dragonflye\n\n"
        "about:\n"
        "  home: https://github.com/rpetit3/{{ name }}\n"
        "  license: MIT\n"
        '  summary: "Assemble genomes   from reads"\n'
        "\nextra:\n  identifiers:\n    - doi:10.1/x\n"
    )
    body = {"content": base64.b64encode(meta.encode()).decode()}
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: json.dumps(body).encode())
    assert sync.about("dragonflye", "bioconda/bioconda-recipes", "sha", 5) == (
        "https://github.com/rpetit3/dragonflye",
        "Assemble genomes from reads",
    )


def test_about_missing_fields(sync, monkeypatch):
    meta = "about:\n  license: MIT\n"
    body = {"content": base64.b64encode(meta.encode()).decode()}
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: json.dumps(body).encode())
    assert sync.about("x", "bioconda/bioconda-recipes", "sha", 5) == ("", "")


def test_about_without_content_raises(sync, monkeypatch):
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: b'{"sha": "x"}')
    with pytest.raises(sync.SyncError):
        sync.about("x", "bioconda/bioconda-recipes", "sha", 5)


def test_merge_replaces_fetched_and_keeps_manual(sync):
    previous = [
        row("https://github.com/bioconda/bioconda-recipes/pull/1", "gone"),
        row("https://github.com/bioconda/bioconda-recipes/pull/2", "stays"),
        row("https://example.org/hand-written", "manual"),
    ]
    fetched = {"bioconda": [row("https://github.com/bioconda/bioconda-recipes/pull/3", "new", "2023-01-01")]}
    rows = sync.merge(previous, fetched, failed=set())
    assert [r["tool"] for r in rows] == ["new", "manual"]


def test_merge_keeps_failed_source_rows(sync):
    previous = [row("https://anaconda.org/rpetit3/aspera-connect", "aspera-connect", "2019-09-10")]
    rows = sync.merge(previous, {}, failed={"channel"})
    assert [r["tool"] for r in rows] == ["aspera-connect"]


def test_pr_entries_builds_rows(sync, monkeypatch):
    monkeypatch.setattr(
        sync,
        "merged_prs",
        lambda repo, author, timeout: [
            {"number": 7, "created_at": "2022-09-21T00:00:00Z"},
            {"number": 8, "created_at": "2022-01-01T00:00:00Z"},
        ],
    )

    def fake_added(repo, number, timeout):
        return ["pasty"] if number == 7 else []

    monkeypatch.setattr(sync, "added_recipes", fake_added)
    monkeypatch.setattr(
        sync,
        "api",
        lambda path, timeout: {"head": {"sha": "abc"}, "merged_at": "2022-09-22T10:00:00Z", "title": "Add PaSty recipe"},
    )
    meta = base64.b64encode(b"about:\n  home: https://example.org\n  summary: s\n").decode()
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: json.dumps({"content": meta}).encode())
    assert sync.pr_entries("bioconda", "rpetit3", 5, 500) == [
        {
            "title": "Submitted PaSty to Bioconda",
            "date": "2022-09-22",
            "pr_url": "https://github.com/bioconda/bioconda-recipes/pull/7",
            "pr_name": "bioconda/bioconda-recipes#7",
            "tool": "PaSty",
            "tool_url": "https://example.org",
            "description": "s",
        }
    ]


def test_drop_shadowed_keeps_only_channel_only_packages(sync):
    channel = [
        row("https://anaconda.org/rpetit3/bactopia", "bactopia"),
        row("https://anaconda.org/rpetit3/perl-db_file", "perl-db_file"),
        row("https://anaconda.org/rpetit3/medaka", "medaka"),
    ]
    recipes = [row("https://github.com/bioconda/bioconda-recipes/pull/1", "bactopia"),
               row("https://github.com/bioconda/bioconda-recipes/pull/2", "perl-db_file")]
    assert [r["tool"] for r in sync.drop_shadowed(channel, recipes)] == ["medaka"]


def test_merge_keeps_listed_extra_pr(sync):
    url = sync.EXTRA_PRS[0]
    rows = sync.merge([row(url, "peregrine-2021")], {"bioconda": []}, failed=set())
    assert [r["tool"] for r in rows] == ["peregrine-2021"]


@pytest.mark.parametrize(
    ("recipe", "title", "expected"),
    [
        ("phiercc", "add recipe for pHierCC", "pHierCC"),
        ("ismapper", "Added ISMapper v2.0 recipe", "ISMapper"),
        ("clinker-py", "add reciper for clinker-py", "clinker-py"),
        ("vadr", "add recipe for vadr", "vadr"),
        ("peregrine-2021", "Jc add peregrine 2021", "peregrine-2021"),
        ("vadr", "add recipe for `vadr`", "vadr"),
    ],
)
def test_display_name(sync, recipe, title, expected):
    assert sync.display_name(recipe, title) == expected


def test_pr_entries_falls_back_to_pr_url_without_home(sync, monkeypatch):
    monkeypatch.setattr(sync, "merged_prs", lambda repo, author, timeout: [{"number": 9, "created_at": "2022-01-01T00:00:00Z"}])
    monkeypatch.setattr(sync, "added_recipes", lambda repo, number, timeout: ["bare"])
    monkeypatch.setattr(sync, "api", lambda path, timeout: {"head": {"sha": "abc"}, "merged_at": "2022-01-02T00:00:00Z", "title": "add bare recipe"})
    meta = base64.b64encode(b"about:\n  summary: s\n").decode()
    monkeypatch.setattr(sync, "fetch", lambda url, timeout: json.dumps({"content": meta}).encode())
    assert sync.pr_entries("staged", "rpetit3", 5, 500)[0]["tool_url"] == "https://github.com/conda-forge/staged-recipes/pull/9"


def test_channel_entries_falls_back_to_package_page(sync, monkeypatch):
    monkeypatch.setattr(sync, "channel_names", lambda user, timeout: ["bare"])
    monkeypatch.setattr(
        sync,
        "fetch",
        lambda url, timeout: json.dumps({"summary": "s", "files": [{"upload_time": "2021-03-04 05:06:07+00:00"}]}).encode(),
    )
    entry = sync.channel_entries("rpetit3", 5)[0]
    assert entry["tool_url"] == "https://anaconda.org/rpetit3/bare"
    assert entry["date"] == "2021-03-04"


def test_merge_keeps_both_recipes_of_one_pr(sync):
    fetched = {
        "bioconda": [
            row("https://github.com/bioconda/bioconda-recipes/pull/39215", "bactopia-qc"),
            row("https://github.com/bioconda/bioconda-recipes/pull/39215", "bactopia-gather"),
        ]
    }
    assert [r["tool"] for r in sync.merge([], fetched, failed=set())] == ["bactopia-gather", "bactopia-qc"]


def test_merge_sorts_newest_first(sync):
    fetched = {
        "bioconda": [row("https://github.com/bioconda/bioconda-recipes/pull/1", "old", "2019-01-01"),
                     row("https://github.com/bioconda/bioconda-recipes/pull/2", "new", "2022-01-01")],
        "channel": [row("https://anaconda.org/rpetit3/x", "aaa", "2022-01-01")],
    }
    rows = sync.merge([], fetched, failed=set())
    assert [(r["tool"], r["date"]) for r in rows] == [("aaa", "2022-01-01"), ("new", "2022-01-01"), ("old", "2019-01-01")]


def test_render_shape_and_quoting(sync):
    text = sync.render(
        [row("https://anaconda.org/rpetit3/x", "x", "2020-01-01") | {"description": "a: b", "tool_url": ""}],
        "2026-01-01T00:00:00Z",
        {"staged"},
    )
    assert text.startswith("# generated by scripts/sync_conda_submissions.py; do not edit\n_meta:\n")
    assert '  as_of: "2026-01-01T00:00:00Z"\n  incomplete:\n    - staged\n' in text
    assert '    description: "a: b"\n' in text
    assert "    tool_url: ''\n" in text or "    tool_url: \"\"\n" in text
    assert text.index("  - title:") < text.index("    date:")
    assert text.endswith("\n\n") is False


def test_render_empty(sync):
    assert sync.render([], "2026-01-01T00:00:00Z", set()).endswith("conda: []\n")


def test_previous_entries_reads_rows(tmp_path):
    spec = importlib.util.spec_from_file_location("sync_conda_submissions", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "volunteer.yml"
    path.write_text(
        "_meta:\n  as_of: \"2020-01-01T00:00:00Z\"\nconda:\n  - pr_url: https://x\n    date: 2022-09-22\n",
        encoding="utf-8",
    )
    assert module.previous_entries(path) == [{"pr_url": "https://x", "date": "2022-09-22"}]