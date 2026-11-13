# robertpetit.com

Personal site for Robert A. Petit III, built with Hugo and the `github-style`
theme.

## Local development

```bash
conda env create -f environment.yml
conda run -n ctx-robertpetit.com-1-dev hugo server --port 1515 --buildDrafts --buildFuture
```

Open http://127.0.0.1:1515.

PDFs under `static/pdf/` are Git LFS objects. The env includes `git` and
`git-lfs`; use the env for Git commands so the hooks resolve.

```bash
conda run -n ctx-robertpetit.com-1-dev git lfs install
conda run -n ctx-robertpetit.com-1-dev git lfs pull
```

## Publication sync

`scripts/sync_publications.py` pulls the OpenAlex author profile, creates missing
publication entries with SEO slugs (`<year>-<title-words>`), and downloads
open-access PDFs to `static/pdf/<slug>.pdf`.

- Existing DOIs (case-insensitive), normalized titles, slugs and PDFs are never
  overwritten, except a stored preprint is upgraded in place when the published
  article appears.
- Dry-run is the default. `--apply` writes files.
- Only works with a DOI, accepted type and OA PDF candidates are considered.
- Citation counts are written to `data/citations-count.yml` on `--apply` runs;
  pass `--citations-out` to redirect them.
- Numbered conference abstracts are excluded unless `--include-abstracts` is set.
- Byline lists are capped at `--max-authors` (default 20) plus `et al.`; the
  profile author stays visible when beyond the cap.
- PDFs are validated as real PDFs (magic bytes, minimum size); failed downloads
  leave `pdf` out of the front matter.
- `--include-preprints` adds preprints; version variants collapse by title.
  Preprint entries carry `preprint = true` and `preprint_version`. A newer
  version of the same DOI base rewrites in place; older versions never
  downgrade. A later published article rewrites the entry and drops both flags.

```bash
export OPENALEX_API_KEY=...
export OPENALEX_AUTHOR_PROFILE=https://openalex.org/authors/A5004170724

# Preview
conda run -n ctx-robertpetit.com-1-dev python scripts/sync_publications.py \
  --since-year 2011 --report report.json

# Write
conda run -n ctx-robertpetit.com-1-dev python scripts/sync_publications.py \
  --since-year 2011 --with-pdfs --apply --report report.json
```

`--author-name` (or `OPENALEX_AUTHOR_NAME`) controls the bolded byline used for
the profile author. `--types`, `--max-new`, `--max-authors`, `--include-abstracts`,
`--skip-pdfs` and `--timeout` are available for automation.

`.github/workflows/sync-publications.yml` runs weekly (Mondays 06:00 UTC) and
from **Actions > Sync Publications > Run workflow**. It tests, syncs, builds,
then opens a PR with the report summary. Configure the `OPENALEX_API_KEY` and
`OPENALEX_AUTHOR_PROFILE` repository secrets; the profile secret falls back to
the hardcoded author ID. `GITHUB_TOKEN` is built in; set an optional `GH_PAT`
secret to author pushes and PRs as your account. Keep the merge step human:
OpenAlex metadata can lag behind or contain duplicate records.

## Software counts

`scripts/collect_software_counts.py` writes `data/software-counts.yml`, which
the software and CV pages render. Tool metadata comes from the pages themselves:
each `content/software/*.md` needs a public GitHub `link` (or `repo:`) and sets
`conda: true` when the title is also a Bioconda package. Adding a page is all
that is needed to track a tool, and the collector warns about public repos under
the tracked owners that have no page.

- Stars and downloads come from [`boast`](https://github.com/mbhall88/boast).
  Every run writes a dated snapshot under `metrics/snapshots/`, keeping the last
  26, so numbers can be re-rendered and diffed later.
- The collector rejects unknown snapshot schemas (`SUPPORTED_SCHEMA`), so a
  newer `boast` fails loudly instead of misparsing.
- Citation counts are read from `data/citations-count.yml`, which
  `sync_publications.py` rewrites weekly from the publication's `paper_doi`
  matches, so they move on the sync schedule, not the counts schedule.
- Only `rpetit3`, `bactopia` and `staphopia` repositories are accepted; any
  other owner fails the run. `scripts/software_exclude.txt` lists public repos
  under those owners that are not software: sites, tests, placeholders.

```bash
export GITHUB_TOKEN=...          # raises the GitHub rate limit
conda run -n ctx-robertpetit.com-1-dev python scripts/collect_software_counts.py
```

`.github/workflows/update-counts.yml` runs daily and from **Actions > Latest
Counts > Run workflow**. OpenAlex rate-limits the repo mention searches, which
the site does not render; those warnings do not touch stars, downloads or
citations.

## Tests

```bash
conda run -n ctx-robertpetit.com-1-dev python -m pytest tests -q
```