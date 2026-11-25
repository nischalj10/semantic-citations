"""Fetch a paper's full text as HTML from arXiv. Free, unlike OpenAlex full text.

Two hosts serve the same LaTeXML HTML:

  ar5iv.labs.arxiv.org   arXiv Labs' HTML mirror; its robots.txt sets no crawl delay
  arxiv.org/html         the main site; its robots.txt asks for 15 seconds between requests

ar5iv is tried first and the main site is the fallback for papers ar5iv does
not have yet. Requests go one at a time with a pause between them, and every
page is cached on disk, so each paper is only ever fetched once.
"""

from __future__ import annotations

import re
import time

import requests

from .config import CACHE

USER_AGENT = "semantic-citations (+https://github.com/nischalj10/semantic-citations)"
# name -> (URL template, seconds between requests)
SOURCES = {
    "ar5iv": ("https://ar5iv.labs.arxiv.org/html/{id}", 3.0),
    "arxiv": ("https://arxiv.org/html/{id}", 15.0),
}
_last_request: dict[str, float] = {}


def arxiv_id_of(work: dict) -> str | None:
    """The arXiv ID of an OpenAlex work, from its DOI or any of its locations."""
    places = [work.get("doi") or ""]
    for loc in work.get("locations") or []:
        places += [loc.get("landing_page_url") or "", loc.get("pdf_url") or ""]
    for place in places:
        m = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", place, re.I) or re.search(r"10\.48550/arxiv\.(\d{4}\.\d{4,5})", place, re.I)
        if m:
            return m.group(1)
    return None


def _get(source: str, arxiv_id: str) -> requests.Response:
    template, gap = SOURCES[source]
    wait = _last_request.get(source, 0.0) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return requests.get(template.format(id=arxiv_id), headers={"User-Agent": USER_AGENT}, allow_redirects=False, timeout=60)
    finally:
        _last_request[source] = time.monotonic()


def _path(arxiv_id: str, source: str):
    return CACHE / "arxiv" / source / f"{arxiv_id}.html"


def is_cached(arxiv_id: str) -> bool:
    return _path(arxiv_id, "ar5iv").exists()


def fetch_html(arxiv_id: str, source: str = "ar5iv") -> str | None:
    """The paper's HTML from one source, or None when that source has no usable HTML.

    ar5iv keeps the version it converted, which can be older than the latest
    one, so a caller that does not find what it needs should try "arxiv" next.
    """
    path = _path(arxiv_id, source)
    if path.exists():
        text = path.read_text(encoding="utf-8")
        return text or None  # an empty file records "nothing usable here"
    r = _get(source, arxiv_id)
    if r.status_code == 429:
        time.sleep(min(float(r.headers.get("Retry-After") or 30), 120))
        r = _get(source, arxiv_id)
    r.encoding = "utf-8"
    # A missing paper redirects to its abstract page (ar5iv) or 404s (arxiv.org);
    # a failed conversion is a page with no reference list.
    usable = r.status_code == 200 and "ltx_bibitem" in r.text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(r.text if usable else "", encoding="utf-8")
    return r.text if usable else None
