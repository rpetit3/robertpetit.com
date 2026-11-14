"""Tests for scripts/sync_publications.py."""

from __future__ import annotations

import shutil
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_publications as sp  # noqa: E402

PDF_BYTES = b"%PDF-1.7\n" + b"x" * 20_000


def work(doi: str, title: str, **overrides: object) -> dict:
    record = {
        "id": f"https://openalex.org/{doi}",
        "doi": f"https://doi.org/{doi}",
        "title": title,
        "publication_year": 2024,
        "publication_date": "2024-03-04",
        "type": "article",
        "open_access": {"is_oa": True},
        "content_urls": {"pdf": f"https://example.org/{doi}.pdf"},
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A5004170724",
                    "display_name": "Robert A. Petit III",
                }
            },
            {
                "author": {
                    "id": "https://openalex.org/A1",
                    "display_name": "Jane Q. Doe",
                }
            },
        ],
        "biblio": {"volume": "10", "issue": "2", "first_page": "1", "last_page": "9"},
        "locations": [],
        "keywords": [{"display_name": "Staphylococcus aureus"}],
        "primary_location": {"source": {"display_name": "Journal of Tests"}},
        "primary_topic": {"subfield": {"display_name": "Microbiology"}},
        "is_retracted": False,
    }
    record.update(overrides)
    return record


class NormalizeTests(unittest.TestCase):
    def test_normalize_doi_strips_prefix_case_and_trailing_period(self):
        self.assertEqual(
            sp.normalize_doi("https://doi.org/10.1128/JB.05863-11."),
            "10.1128/jb.05863-11",
        )

    def test_normalize_title_ignores_punctuation_markup_and_labels(self):
        self.assertEqual(
            sp.normalize_title("Erratum to: Draft *Genome* of the whale-shark!"),
            "draftgenomeofthewhaleshark",
        )


class SlugTests(unittest.TestCase):
    def test_slug_is_seo_friendly_and_drops_stopwords(self):
        slug = sp.slugify_title(
            2021,
            "A Global Metagenomic Map of Urban Microbiomes & Antimicrobial Resistance",
        )
        self.assertEqual(
            slug,
            "2021-global-metagenomic-map-urban-microbiomes-antimicrobial-resistance",
        )

    def test_slug_is_capped_at_word_boundary(self):
        slug = sp.slugify_title(2026, "Staphylococcus aureus " * 20, max_len=60)
        self.assertLessEqual(len(slug), 60)
        self.assertFalse(slug.endswith("-"))

    def test_slug_is_ascii(self):
        self.assertEqual(sp.slugify_title(2026, "Candida auris – São Paulo"), "2026-candida-auris-sao-paulo")

    def test_unique_slug_appends_counter(self):
        taken = {"2026-thing"}
        self.assertEqual(sp.unique_slug("2026-thing", taken), "2026-thing-2")
        self.assertIn("2026-thing-2", taken)


class TagTests(unittest.TestCase):
    def test_aliases_fold_to_canonical(self):
        self.assertEqual(sp.canonical_tag("MRSA"), "staphylococcus")
        self.assertEqual(sp.canonical_tag("Staphylococcus aureus"), "staphylococcus")
        self.assertEqual(sp.canonical_tag("antimicrobial resistance"), "resistance")
        self.assertEqual(sp.canonical_tag("big data"), "data")

    def test_unknown_keyword_uses_fallback(self):
        self.assertEqual(sp.canonical_tag("brand new topic"), "genomic")

    def test_alias_targets_are_canonical(self):
        for target in sp.TAG_ALIASES.values():
            if target:
                self.assertIn(target, sp.CANONICAL_TAGS)

    def test_derive_tags_dedupes_and_caps_at_three(self):
        record = {
            "keywords": [
                {"display_name": "MRSA"},
                {"display_name": "staphylococcus"},
                {"display_name": "genomic"},
                {"display_name": "virulence"},
            ]
        }
        self.assertEqual(sp.derive_tags(record), ["staphylococcus", "genomic", "virulence"])

    def test_derive_tags_uses_topic_then_fallback(self):
        record = {"primary_topic": {"subfield": {"display_name": "MRSA"}}}
        self.assertEqual(sp.derive_tags(record), ["staphylococcus"])
        self.assertEqual(sp.derive_tags({}), ["genomic"])


class TextTests(unittest.TestCase):
    def test_reconstruct_abstract_orders_words(self):
        inverted = {"world": [1], "hello": [0], "again": [2]}
        self.assertEqual(sp.reconstruct_abstract(inverted), "hello world again")

    def test_summarize_takes_first_sentence_and_truncates(self):
        self.assertEqual(sp.summarize("One. Two.", "Title"), "One.")
        summary = sp.summarize("word " * 100, "Title", limit=20)
        self.assertLessEqual(len(summary), 21)
        self.assertTrue(summary.endswith("…"))

    def test_author_pairs_marks_profile_author(self):
        pairs = sp.author_pairs(
            work("10.1/x", "T"), "A5004170724", "Robert A. Petit III", 5
        )
        self.assertIn(("Robert A. Petit III", True), pairs)
        self.assertIn(("Jane Q. Doe", False), pairs)

    def test_author_pairs_uses_crossref_when_openalex_is_capped(self):
        authorships = [
            {"author": {"id": f"https://openalex.org/A{i}", "display_name": f"Author {i}"}}
            for i in range(100)
        ]
        record = work("10.1/x", "T", authorships=authorships)
        names = ["Lauren Mak", "Robert A. Petit III", "Jane Doe"]
        with patch.object(sp, "crossref_author_names", return_value=names):
            pairs = sp.author_pairs(record, "A5004170724", "Robert A. Petit III", 5)
        self.assertEqual(pairs[1], ("Robert A. Petit III", True))
        self.assertEqual(len(pairs), 3)

    def test_profile_author_match_requires_family_and_initial(self):
        self.assertTrue(sp.profile_author_match("Robert A. Petit III", "Robert A. Petit III"))
        self.assertFalse(sp.profile_author_match("Jane Petit", "Robert A. Petit III"))


class EntryTests(unittest.TestCase):
    def test_build_entry_produces_parsable_front_matter(self):
        entry = sp.build_entry(work("10.1/x", 'A "quoted" title'), "A5004170724", set())
        payload = tomllib.loads(entry.front_matter.split("+++")[1])
        self.assertEqual(payload["title"], 'A "quoted" title')
        self.assertEqual(payload["type"], "publication")
        self.assertEqual(payload["doi"], "10.1/x")
        self.assertIn("***Robert A. Petit III***", payload["authors"])
        self.assertNotIn("pdf", payload)
        self.assertEqual(payload["tags"], ["staphylococcus"])

    def test_build_entry_caps_authors_but_keeps_profile_author(self):
        authorships = [
            {"author": {"id": f"https://openalex.org/A{i}", "display_name": f"Author {i}"}}
            for i in range(15)
        ]
        authorships.insert(
            12,
            {
                "author": {
                    "id": "https://openalex.org/A5004170724",
                    "display_name": "Robert A. Petit III",
                }
            },
        )
        record = work("10.1/x", "T", authorships=authorships)
        entry = sp.build_entry(record, "A5004170724", set(), max_authors=5)
        payload = tomllib.loads(entry.front_matter.split("+++")[1])
        self.assertEqual(len(payload["authors"]), 7)
        self.assertEqual(payload["authors"][5], "***Robert A. Petit III***")
        self.assertEqual(payload["authors"][-1], "et al.")

    def test_build_entry_does_not_duplicate_profile_author_in_head(self):
        authorships = work("10.1/x", "T")["authorships"]
        authorships.extend(
            {"author": {"id": f"https://openalex.org/A{i}", "display_name": f"A {i}"}}
            for i in range(12)
        )
        record = work("10.1/x", "T", authorships=authorships)
        entry = sp.build_entry(record, "A5004170724", set(), max_authors=5)
        payload = tomllib.loads(entry.front_matter.split("+++")[1])
        self.assertEqual(payload["authors"].count("***Robert A. Petit III***"), 1)

    def test_load_existing_collects_doi_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            pdfs = Path(tmp) / "pdf"
            content.mkdir()
            pdfs.mkdir()
            (content / "2020-old.md").write_text(
                '+++\ntitle = "Old Paper"\ndoi = "10.1128/JB.1"\n+++\n',
                encoding="utf-8",
            )
            index = sp.load_existing(content, pdfs)
            self.assertIn("10.1128/jb.1", index.dois)
            self.assertIn("2020-old", index.slugs)

    def test_fetch_pdf_authenticates_openalex_content_host(self):
        response = MagicMock()
        response.status_code = 200
        response.iter_content.return_value = [PDF_BYTES]
        with patch.object(sp.curl_requests, "get", return_value=response) as get:
            blob = sp.fetch_pdf(
                "https://content.openalex.org/works/W1.pdf", 5, "secret"
            )
        self.assertEqual(blob, PDF_BYTES)
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer secret")

    def test_pdf_validation_rejects_html(self):
        self.assertTrue(sp.is_pdf(PDF_BYTES))
        self.assertFalse(sp.is_pdf(b"<!doctype html>"))

    def test_oa_pdf_urls_requires_open_access(self):
        closed = work("10.1/x", "T", open_access={"is_oa": False})
        self.assertEqual(sp.oa_pdf_urls(closed), [])

    def test_clean_title_removes_space_before_punctuation(self):
        self.assertEqual(sp.clean_title(" Candida auris : trends "), "Candida auris: trends")

    def test_crossref_person_name_moves_suffix_out_of_family(self):
        person = {"given": "Robert A Petit", "family": "III"}
        self.assertEqual(sp.crossref_person_name(person), "Robert A Petit III")

    def test_oa_pdf_urls_includes_pmc_render_fallback(self):
        record = work(
            "10.1/x",
            "T",
            content_urls={},
            locations=[
                {
                    "is_oa": True,
                    "pdf_url": None,
                    "landing_page_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234/",
                }
            ],
        )
        self.assertIn(
            "https://europepmc.org/articles/PMC1234?pdf=render",
            sp.oa_pdf_urls(record),
        )

    def test_oa_pdf_urls_handles_unprefixed_pmcid(self):
        record = work(
            "10.1/x",
            "T",
            content_urls={},
            ids={"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/12548784"},
            locations=[],
        )
        self.assertIn(
            "https://europepmc.org/articles/PMC12548784?pdf=render",
            sp.oa_pdf_urls(record),
        )

    def test_summarize_strips_section_labels(self):
        self.assertEqual(
            sp.summarize("Abstract Background: MRSA is bad. More text.", "T"),
            "MRSA is bad.",
        )

    def test_clean_abstract_strips_repeated_abstract_label(self):
        self.assertEqual(sp.clean_abstract("Abstract Abstract Real text"), "Real text")

    def test_numbered_abstract_requires_supplement_pages(self):
        record = work("10.1/x", "852. A Poster", biblio={"first_page": "S1"})
        self.assertTrue(sp.is_numbered_abstract(record))
        self.assertFalse(sp.is_numbered_abstract(work("10.1/y", "852. Not a poster")))

    def test_citation_with_empty_biblio_skips_none(self):
        citation = sp.render_citation(
            ["Robert A. Petit III"], "A Title", "*eLife*", {}, 2026
        )
        self.assertEqual(citation, "Petit, R. A., 3rd A Title. eLife (2026).")
        self.assertNotIn("None", citation)

    def test_citation_uses_suffix_and_profile_name(self):
        citation = sp.render_citation(
            ["Robert A. Petit III", "Jane Q. Doe"],
            "A Title",
            "*Journal*",
            {"volume": "1"},
            2024,
        )
        self.assertIn("Petit, R. A., 3rd", citation)


class CliTests(unittest.TestCase):
    def run_cli(
        self,
        args: list[str],
        works: list[dict],
        fetch_pdf=None,
        existing_files: dict[str, str] | None = None,
    ):
        runner = CliRunner()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        content = Path(tmp) / "content"
        pdfs = Path(tmp) / "pdf"
        content.mkdir()
        pdfs.mkdir()
        files = existing_files or {
            "2024-existing.md": '+++\ntitle = "Existing"\ndoi = "10.1/EXISTING"\n+++\n'
        }
        for name, body in files.items():
            (content / name).write_text(body, encoding="utf-8")
        patch_pdf = (
            patch.object(sp, "fetch_pdf", side_effect=fetch_pdf)
            if fetch_pdf
            else patch.object(sp, "fetch_pdf", return_value=PDF_BYTES)
        )
        with (
            patch.object(sp, "fetch_works", return_value=works),
            patch_pdf,
        ):
            result = runner.invoke(
                sp.main,
                [
                    "--author",
                    "A5004170724",
                    "--content-dir",
                    str(content),
                    "--pdf-dir",
                    str(pdfs),
                    "--citations-out",
                    str(Path(tmp) / "citations-count.yml"),
                    *args,
                ],
            )
        return result, content, pdfs

    def test_dry_run_writes_nothing(self):
        result, content, pdfs = self.run_cli(
            ["--dry-run"], [work("10.1/new", "A New Paper")]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(list(content.glob("*.md"))), 1)
        self.assertEqual(list(pdfs.glob("*.pdf")), [])

    def test_apply_skips_duplicates_and_retractions(self):
        works = [
            work("10.1/EXISTING", "Existing"),
            work("10.1/new", "A New Paper"),
            work("10.1/retracted", "Retracted", is_retracted=True),
        ]
        result, content, pdfs = self.run_cli(["--apply"], works)
        self.assertEqual(result.exit_code, 0, result.output)
        names = {path.name for path in content.glob("*.md")}
        self.assertEqual(names, {"2024-existing.md", "2024-new-paper.md"})
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertIn('pdf = "/pdf/2024-new-paper.pdf"', body)
        self.assertTrue((pdfs / "2024-new-paper.pdf").exists())

    def test_apply_without_pdf_urls_omits_pdf_field(self):
        records = [work("10.1/new", "A New Paper", content_urls={})]
        result, content, _ = self.run_cli(["--apply"], records)
        self.assertEqual(result.exit_code, 0, result.output)
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertNotIn("pdf =", body)

    def test_abstract_containing_pdf_does_not_abort(self):
        record = work(
            "10.1/new",
            "A New Paper",
            abstract_inverted_index={"pdf": [0], "metadata": [1]},
        )
        result, content, _ = self.run_cli(["--apply"], [record])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((content / "2024-new-paper.md").exists())

    def test_poster_abstract_excluded_by_default(self):
        record = work(
            "10.1/poster", "852. A Poster", biblio={"first_page": "S1", "last_page": "S2"}
        )
        result, content, _ = self.run_cli(["--apply"], [record])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual({path.name for path in content.glob("*.md")}, {"2024-existing.md"})

    def test_include_abstracts_keeps_poster(self):
        record = work(
            "10.1/poster", "852. A Poster", biblio={"first_page": "S1", "last_page": "S2"}
        )
        result, content, _ = self.run_cli(["--apply", "--include-abstracts"], [record])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((content / "2024-poster.md").exists())

    def test_build_entry_marks_preprints(self):
        entry = sp.build_entry(
            work("10.7554/elife.1", "T", type="preprint"), "A5004170724", set()
        )
        payload = tomllib.loads(entry.front_matter.split("+++")[1])
        self.assertTrue(payload["preprint"])

    def test_apply_upgrades_flagged_elife_preprint(self):
        existing = {
            "2024-new-paper.md": (
                '+++\ntitle = "A New Paper"\ndoi = "10.7554/elife.109393.1"\n'
                'journal = "*eLife*"\npreprint = true\n+++\n'
            )
        }
        works = [work("10.7554/elife.109393", "A New Paper", type="article")]
        result, content, _ = self.run_cli(
            ["--apply"], works, existing_files=existing
        )
        self.assertEqual(result.exit_code, 0, result.output)
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertIn('doi = "10.7554/elife.109393"', body)
        self.assertNotIn("preprint = true", body)

    def test_apply_bumps_preprint_version_without_downgrade(self):
        existing = {
            "2024-new-paper.md": (
                '+++\ntitle = "A New Paper"\ndoi = "10.7554/elife.109393.1"\n'
                'journal = "*eLife*"\npreprint = true\npreprint_version = 1\n+++\n'
            )
        }
        works = [
            work("10.7554/elife.109393.3", "A New Paper", type="preprint"),
            work("10.7554/elife.109393.2", "A New Paper", type="preprint"),
        ]
        result, content, _ = self.run_cli(["--apply"], works, existing_files=existing)
        self.assertEqual(result.exit_code, 0, result.output)
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertIn('doi = "10.7554/elife.109393.3"', body)
        self.assertIn("preprint_version = 3", body)
        self.assertIn("preprint = true", body)
        

    def test_older_preprint_version_is_skipped(self):
        existing = {
            "2024-new-paper.md": (
                '+++\ntitle = "A New Paper"\ndoi = "10.7554/elife.109393.3"\n'
                'journal = "*eLife*"\npreprint = true\npreprint_version = 3\n+++\n'
            )
        }
        works = [work("10.7554/elife.109393.2", "A New Paper", type="preprint")]
        result, content, _ = self.run_cli(["--apply"], works, existing_files=existing)
        self.assertEqual(result.exit_code, 0, result.output)
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertIn('doi = "10.7554/elife.109393.3"', body)
        new_pdf = b"%PDF-1.7\n" + b"y" * 20_000
        existing = {
            "2024-new-paper.md": (
                '+++\ntitle = "A New Paper"\ndoi = "10.1101/2024.01.01.1"\n'
                'journal = "*bioRxiv*"\n+++\n'
            )
        }
        works = [work("10.1/published", "A New Paper")]
        result, content, pdfs = self.run_cli(
            ["--apply"], works, fetch_pdf=lambda url, timeout, api_key=None: new_pdf,
            existing_files=existing,
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual({path.name for path in content.glob("*.md")}, {"2024-new-paper.md"})
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertIn('doi = "10.1/published"', body)
        self.assertNotIn("bioRxiv", body)
        self.assertEqual((pdfs / "2024-new-paper.pdf").read_bytes(), new_pdf)

    def test_article_same_title_as_article_is_skipped(self):
        existing = {
            "2024-new-paper.md": '+++\ntitle = "A New Paper"\ndoi = "10.1/old"\n+++\n'
        }
        works = [work("10.1/new", "A New Paper")]
        result, content, _ = self.run_cli(["--apply"], works, existing_files=existing)
        self.assertEqual(result.exit_code, 0, result.output)
        body = (content / "2024-new-paper.md").read_text(encoding="utf-8")
        self.assertIn('doi = "10.1/old"', body)


class CitationsTests(unittest.TestCase):
    def test_writes_only_present_dois(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "citations-count.yml"
            saved = sp.write_citations(
                [work("10.1/kept", "Kept", cited_by_count=7), work("10.1/absent", "Absent", cited_by_count=2)],
                {"10.1/kept"},
                target,
                apply=True,
            )
            body = target.read_text(encoding="utf-8")
        self.assertEqual(saved, 1)
        self.assertIn('"10.1/kept": 7', body)
        self.assertNotIn("absent", body)
        self.assertIn("_meta", body)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "citations-count.yml"
            saved = sp.write_citations([work("10.1/kept", "Kept", cited_by_count=7)], {"10.1/kept"}, target, apply=False)
            self.assertEqual(saved, 1)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()