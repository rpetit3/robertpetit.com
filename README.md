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

`.github/workflows/update-data.yml` runs Mondays 01:30 UTC and from
**Actions > Weekly Data Refresh > Run workflow**, shared with the pull request
and conda submission refreshes: one environment, one build, one push. A source
that fails does not stop the others; the run still commits what it got and
fails at the end. OpenAlex rate-limits the repo mention searches, which the site
does not render; those warnings do not touch stars, downloads or citations.

## Volunteer conda submissions

`scripts/sync_conda_submissions.py` rebuilds the conda table on `/volunteer/`
into `data/volunteer.yml`. Rows come from three public sources, and no hand
editing is needed:

- Merged pull requests by `rpetit3` that add `recipes/<tool>/meta.yaml` to
  `bioconda/bioconda-recipes` or `conda-forge/staged-recipes`. The changed files
  decide what is a new recipe; the PR title only supplies the display casing.
- Packages on the `anaconda.org/rpetit3` channel, read from its repodata and the
  anaconda.org package API.

Tool, link and description are lifted from the recipe's `about:` block
(`home`, `summary`) or the channel package metadata. Dates are merge dates, or
the earliest channel upload. A missing `home` falls back to the pull request or
package page, so no row self-links.

- A source that fails keeps its previous rows and is named under
  `_meta.incomplete`; the page shows stale data instead of losing history.
- Rows whose `pr_url` matches no source (hand-written) survive every run.
  `EXTRA_PRS` in the script lists recipes written by the author but opened by
  somebody else, which an author search cannot find.

```bash
export GITHUB_TOKEN=...          # required, the run makes ~450 API calls
conda run -n ctx-robertpetit.com-1-dev python scripts/sync_conda_submissions.py --dry-run
```

`.github/workflows/update-data.yml` refreshes the table in the Mondays 01:30 UTC
run (**Actions > Weekly Data Refresh > Run workflow** to force one). Only merged
recipes are listed, so a closed-without-merge submission never appears.

## Site health

`.github/workflows/site-health.yml` probes production daily (05:17 UTC) and from
**Actions > Site Health > Run workflow**: status codes on the main pages, a
content marker per page, certificate chain and expiry, and the http and apex
redirects. A lapsed Netlify certificate once broke the site for weeks, hence the
certificate window: it warns at 14 days and fails at 3.

- Any failed probe fails the run and opens a `site-down` issue with the run URL;
  later failures append a comment instead of a second issue, and the next green
  run closes it.
- Point `SITE`/`HOST` at `http://localhost:1515` to exercise the probes against a
  local build; the TLS and redirect probes fail there by design.

## Tests

```bash
conda run -n ctx-robertpetit.com-1-dev python -m pytest tests -q
```