# AGENTS.md

Personal Hugo site for Robert A. Petit III at https://www.robertpetit.com/.
Pages render from Markdown front matter and `data/*.yml`; Netlify builds and
deploys `main` using `netlify.toml`.

## Environment

`hugo` is not on the global PATH. Every command runs in the declared env:

```bash
conda run -n ctx-robertpetit.com-1-dev hugo --gc --minify -d /tmp/site-build
conda run -n ctx-robertpetit.com-1-dev python -m pytest tests -q
conda run -n ctx-robertpetit.com-1-dev actionlint
```

`public/`, `resources/`, `.pytest_cache/` and `metrics/snapshots/` are
gitignored. `themes/github-style` is a pinned submodule; run
`git submodule update --init` before the first build.

## Never hand-edit

| File | Writer |
|---|---|
| `data/citations-count.yml` | `scripts/sync_publications.py` |
| `data/software-counts.yml` | `scripts/collect_software_counts.py` |
| `data/volunteer.yml` | `scripts/sync_conda_submissions.py` |
| `data/github.json`, `data/merged.json` | GraphQL steps in `.github/workflows/update-data.yml` |
| `metrics/manifest.toml` | `scripts/collect_software_counts.py` |

Hand-editable: `data/cv.yml`, `data/assets.toml`, and everything under
`content/`.

## Content rules

- Front matter delimiter follows the section: `+++` (TOML) under
  `content/publication/`, `---` (YAML) under `content/software/`. Hugo detects
  the format per file, so a cross-section copy still renders, but a mismatched
  pair (`---` opened, `+++` closed) fails the build. `hugo new <section>/<name>.md`
  copies the matching archetype.
- Publication and software bodies are empty; every field is front matter.
- `data/cv.yml` employment has exactly one `primary: true` row, listed first;
  the CV orders primary, other current, then past, and
  `tests/test_cv_data.py` enforces it.
- New PDFs go to `static/pdf/<slug>.pdf` through LFS: `*.pdf` is LFS-filtered,
  so the repository stores a pointer and the working tree keeps the file.
- `content/software/*.md` needs a public GitHub `link` and sets `conda: true`
  when the title is also a Bioconda package; the collector derives counts from
  those fields. Slugs are `<year>-<title-words>` and are permanent.
- `content/publication/` is rewritten by the weekly sync, so edits that the
  sync owns (abstracts, citations, PDFs) only survive while the DOI is absent
  from OpenAlex.

## Scripts

`sync_publications.py` defaults to a dry run and writes only with `--apply`.
`sync_conda_submissions.py` writes by default and takes `--dry-run`, while
`collect_software_counts.py` always writes. `sync_publications.py` needs
`OPENALEX_API_KEY`; the other two need `GITHUB_TOKEN`. Accepted owners are
`rpetit3`, `bactopia`, `staphopia`; `scripts/software_exclude.txt` lists public
non-software repos. Tests pin these contracts, so run pytest after touching a
script. `consolidate_tags.py` rewrites existing tags from HEAD through the alias
map; run it after editing `TAG_ALIASES`.

## Crawler surface

`static/robots.txt` and `static/llms.txt` are served as real files. The
`/* -> /index.html` redirect in `netlify.toml` applies to misses only, so a
crawler path that does not exist returns the homepage with status 200 instead
of a 404. `.github/workflows/site-health.yml` probes both files for
`text/plain` and a marker; keep it green.