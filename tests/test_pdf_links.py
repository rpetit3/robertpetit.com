"""Guard local PDF links against renamed or removed files.

The Netlify catch-all answers a missing PDF with the home page and status 200,
so a broken local link is invisible in production.
"""

import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parents[1]
CV = ROOT / "data" / "cv.yml"
BASE = "https://www.robertpetit.com"

LOCAL_PDF = re.compile(r"(?:https://www\.robertpetit\.com)?(/pdf/[A-Za-z0-9_./-]+\.pdf)")
ANY_PDF_URL = re.compile(r"https?://[^\s\"')]+/pdf/[^\s\"')]+\.pdf")


def sources() -> list[Path]:
    return [CV, *sorted((ROOT / "content").rglob("*.md"))]


def local_refs() -> list[str]:
    return [
        match.group(1)
        for path in sources()
        for match in LOCAL_PDF.finditer(path.read_text(encoding="utf-8"))
    ]


def test_local_pdf_refs_exist():
    refs = local_refs()
    assert refs
    for ref in refs:
        assert (ROOT / "static" / ref.lstrip("/")).exists(), (
            f"{ref} matches no file under static/"
        )


def test_pdf_urls_use_the_canonical_host():
    for path in sources():
        for url in ANY_PDF_URL.findall(path.read_text(encoding="utf-8")):
            assert urlparse(url).netloc == "www.robertpetit.com", (
                f"{url} is not on the canonical host"
            )