"""Sanity tests for data/cv.yml presentations."""

from collections import Counter
from pathlib import Path

import yaml

CV = Path(__file__).parents[1] / "data" / "cv.yml"


def presentations() -> list[dict]:
    return yaml.safe_load(CV.read_text(encoding="utf-8"))["presentations"]


def employment() -> list[dict]:
    return yaml.safe_load(CV.read_text(encoding="utf-8"))["employment"]


def test_every_presentation_has_required_fields():
    for entry in presentations():
        for field in ("title", "conference", "authors", "type", "date"):
            assert entry.get(field), f"{entry.get('title')!r} missing {field}"
        assert entry["type"] in {"talk", "poster"}


def test_authors_is_a_non_empty_list():
    for entry in presentations():
        assert isinstance(entry["authors"], list)
        assert entry["authors"]


def test_no_duplicate_presentations():
    keys = Counter(
        (entry["title"].lower(), entry["conference"].lower(), str(entry["date"]))
        for entry in presentations()
    )
    assert [key for key, count in keys.items() if count > 1] == []


def test_presentations_are_newest_first():
    dates = [str(entry["date"]) for entry in presentations()]
    assert dates == sorted(dates, reverse=True)


def test_ongoing_employment_leads():
    rows = employment()
    assert rows[0].get("primary") is True
    assert [row for row in rows if row.get("primary")] == [rows[0]]
    ongoing = [row for row in rows if str(row["end"]) == "present" and not row.get("primary")]
    assert ongoing
    assert all(str(row["end"]) == "present" for row in rows[: 1 + len(ongoing)])
    assert [str(row["start"]) for row in ongoing] == sorted(
        (str(row["start"]) for row in ongoing), reverse=True
    )
    past = [str(row["start"]) for row in rows[1 + len(ongoing) :]]
    assert past == sorted(past, reverse=True)


def professional_development() -> list[dict]:
    return yaml.safe_load(CV.read_text(encoding="utf-8"))["professional_development"]


def test_professional_development_entries_are_typed_and_named():
    for entry in professional_development():
        assert entry["type"] in {"certification", "training"}
        assert entry["name"]
        assert entry.get("date")
