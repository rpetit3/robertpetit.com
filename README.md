# robertpetit.com

This is my personal site, https://www.robertpetit.com/. It is built with Hugo
and the `github-style` theme, and Netlify deploys `main`. Pages come from
Markdown files and `data/*.yml`.

## Local development

The tools live in a conda env so the versions match production.

```bash
conda env create -f environment.yml
conda run -n ctx-robertpetit.com-1-dev hugo server --port 1515 --buildDrafts --buildFuture
```

Open http://127.0.0.1:1515.

PDFs live in `static/pdf/` and are stored with Git LFS, which keeps large files
out of normal Git history. Use Git from the env so LFS runs:

```bash
conda run -n ctx-robertpetit.com-1-dev git lfs install
conda run -n ctx-robertpetit.com-1-dev git lfs pull
```

## Publications

`scripts/sync_publications.py` reads my OpenAlex author record, adds any missing
papers, gives each one a readable `<year>-<title-words>` URL, and downloads open
PDFs to `static/pdf/`.

- Nothing is overwritten without a reason. A stored preprint is upgraded in
  place when the published article appears.
- A dry run is the default; `--apply` writes.
- A paper needs a DOI and an accepted type; open PDFs are downloaded when
  available.
- Citation counts go to `data/citations-count.yml` on `--apply` runs;
  `--citations-out` sends them elsewhere.
- Numbered conference abstracts are skipped unless `--include-abstracts` is set.
- Author lists stop at `--max-authors` (20 by default) and add `et al.`; my name
  stays visible past the cap.
- Downloads are checked to be real PDFs. A failed download leaves `pdf` out.
- `--include-preprints` adds preprints and folds versions by title. A newer
  version replaces an older one, and a published paper replaces the preprint.
- Keywords become tags through an alias map in `derive_tags`, so new papers
  cannot regrow one-off tags. `scripts/consolidate_tags.py` applies the same map
  to existing entries.

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

`--author-name` (or `OPENALEX_AUTHOR_NAME`) sets the bolded name used for the
profile author. `--types`, `--max-new`, `--max-authors`, `--include-abstracts`,
`--skip-pdfs` and `--timeout` are there for automation.

`.github/workflows/sync-publications.yml` runs every Monday at 06:00 UTC, or
from **Actions > Sync Publications > Run workflow**. It tests, syncs, builds,
and opens a PR with a summary. Set the `OPENALEX_API_KEY` and
`OPENALEX_AUTHOR_PROFILE` secrets; the profile secret falls back to my author
ID. `GITHUB_TOKEN` is built in, and `GH_PAT` is optional if pushes and PRs
should come from my account. I merge by hand because OpenAlex can lag behind or
list duplicate records.

## Software counts

`scripts/collect_software_counts.py` fills `data/software-counts.yml`, which the
software and CV pages show. Each `content/software/*.md` page needs a public
GitHub `link` (or `repo:`) and sets `conda: true` when the title is also a
Bioconda package. Adding a page is all it takes to track a tool, and the script
warns about public repos under the tracked owners that have no page.

- Stars and downloads come from [`boast`](https://github.com/mbhall88/boast).
- Every run saves a dated copy under `metrics/snapshots/`, keeping the last 26,
  so numbers can be re-rendered and compared later.
- The script rejects unknown snapshot formats, so a newer `boast` fails loudly
  instead of being read wrong.
- Citations come from `data/citations-count.yml`, which the publication sync
  rewrites weekly, so they move on that schedule, not this one.
- Only `rpetit3`, `bactopia` and `staphopia` repositories are accepted; any
  other owner fails the run. `scripts/software_exclude.txt` lists public repos
  under those owners that are not software: sites, tests, placeholders.

```bash
export GITHUB_TOKEN=...          # raises the GitHub rate limit
conda run -n ctx-robertpetit.com-1-dev python scripts/collect_software_counts.py
```

`.github/workflows/update-data.yml` runs Mondays 01:30 UTC, or from
**Actions > Weekly Data Refresh > Run workflow**, and shares the pull request
and conda refreshes: one environment, one build, one push. A source that fails
does not stop the others; the run still commits what it got and fails at the
end. OpenAlex rate-limits the repo mention searches, which the site does not
show; those warnings do not touch stars, downloads or citations.

## Volunteer conda submissions

`scripts/sync_conda_submissions.py` rebuilds the conda table on `/volunteer/`
into `data/volunteer.yml` from public sources, so nothing is edited by hand:

- Merged pull requests by `rpetit3` that add `recipes/<tool>/meta.yaml` to
  `bioconda/bioconda-recipes` or `conda-forge/staged-recipes`. The changed files
  decide what is a new recipe; the PR title only supplies the display name.
- Packages on the `anaconda.org/rpetit3` channel, read from the channel data and
  the anaconda.org package API.

The tool, link and description come from the recipe or package page. Dates are
merge dates, or the first upload date. A missing home page falls back to the
pull request or package page, so no row links to itself.

- A source that fails keeps its old rows and is named under `_meta.incomplete`;
  the page shows stale data instead of losing history.
- Hand-written rows survive every run. `EXTRA_PRS` lists recipes I wrote that
  someone else opened, which an author search cannot find.

```bash
export GITHUB_TOKEN=...          # required, the run makes ~450 API calls
conda run -n ctx-robertpetit.com-1-dev python scripts/sync_conda_submissions.py --dry-run
```

`.github/workflows/update-data.yml` refreshes the table in the Mondays 01:30 UTC
run (**Actions > Weekly Data Refresh > Run workflow** to force one). Only merged
recipes are listed, so a closed submission never appears.

## Site health

`.github/workflows/site-health.yml` checks production daily at 05:17 UTC and
from **Actions > Site Health > Run workflow**: status codes, a marker on each
main page, the certificate and its expiry, and the http and apex redirects. A
lapsed certificate once broke the site for weeks, so it warns at 14 days and
fails at 3.

- A failed check fails the run and opens a `site-down` issue with the run URL;
  later failures add a comment instead of a second issue, and the next good run
  closes it.
- Point `SITE` and `HOST` at `http://localhost:1515` to run the checks against a
  local build; the certificate and redirect checks fail there by design.

## Agents and crawlers

`AGENTS.md` holds the environment, generated-file and content notes for coding
agents. `static/robots.txt` and `static/llms.txt` are real files. A missing path
does not return a 404; Netlify sends the home page with a 200, so a new crawler
path has to exist. `site-health.yml` checks both files for `text/plain` and a
marker, and `tests/test_llms_txt.py` fails when an `llms.txt` link stops
working.

## Tests

```bash
conda run -n ctx-robertpetit.com-1-dev python -m pytest tests -q
```