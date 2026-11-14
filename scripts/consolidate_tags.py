#!/usr/bin/env python3
"""Rewrite existing tags through the alias map in sync_publications.py.

The weekly sync only tags new entries, so run this after changing TAG_ALIASES
to bring existing publications and tools in line. Tag lists are read from HEAD,
so the script can be re-run after a partial pass.

Usage: python scripts/consolidate_tags.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from sync_publications import TAG_ALIASES, canonical_tag, tag_slug  # noqa: E402

FILES = [
    *sorted((ROOT / "content" / "publication").glob("*.md")),
    *sorted((ROOT / "content" / "software").glob("*.md")),
]
TOML_TAGS = re.compile(r'^tags\s*=\s*\[(.*)\]$', re.M)
YAML_TAGS = re.compile(r'^tags\s*:\s*\[(.*)\]$', re.M)


def head_tags(path: Path) -> list[str] | None:
    rel = path.relative_to(ROOT)
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, text=True
    )
    text = result.stdout if result.returncode == 0 else path.read_text(encoding="utf-8")
    match = TOML_TAGS.search(text) or YAML_TAGS.search(text)
    return re.findall(r'"([^"]+)"', match.group(1)) if match else None


def remap(tags: list[str]) -> list[str]:
    mapped: list[str] = []
    for tag in tags:
        slug = tag_slug(tag)
        target = TAG_ALIASES[slug] if slug in TAG_ALIASES else canonical_tag(slug)
        if target and target not in mapped:
            mapped.append(target)
    return mapped


def main() -> None:
    empty: list[str] = []
    changed = 0
    for path in FILES:
        tags = head_tags(path)
        if tags is None:
            continue
        mapped = remap(tags)
        if not mapped:
            empty.append(str(path.relative_to(ROOT)))
        text = path.read_text(encoding="utf-8")
        match = TOML_TAGS.search(text) or YAML_TAGS.search(text)
        if not match:
            continue
        value = "[" + ", ".join(f'"{tag}"' for tag in mapped) + "]"
        sep = " =" if match.re is TOML_TAGS else ":"
        expected = f"tags{sep} {value}"
        if match.group(0) == expected:
            continue
        path.write_text(
            text[: match.start()] + expected + text[match.end() :],
            encoding="utf-8",
        )
        changed += 1
    print(f"changed {changed} files")
    if empty:
        print("no tags left:", *empty, sep="\n  ")


if __name__ == "__main__":
    main()