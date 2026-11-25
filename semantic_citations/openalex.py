"""OpenAlex: resolve a paper, list everything that cites it, fetch full text.

Costs on a free key ($1/day): looking up one work is free, a page of citing
works is $0.0001, and each full-text download is $0.01. Full text is cached
on disk, so a paper is only ever paid for once.
"""

from __future__ import annotations

import json
import re
import time

import requests

from .config import CACHE, require

API = "https://api.openalex.org"
CONTENT = "https://content.openalex.org"
FULLTEXT_COST_USD = 0.01


def _get(url: str, params: dict | None = None, *, raw: bool = False):
    params = {**(params or {}), "api_key": require("OPENALEX_API_KEY")}
    for attempt in range(4):
        r = requests.get(url, params=params, timeout=60)
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(2**attempt)
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content if raw else r.json()


def short_id(work: dict | str) -> str:
    return (work if isinstance(work, str) else work["id"]).rsplit("/", 1)[-1]


def to_lookup_key(identifier: str) -> str:
    """Accept an arXiv URL or ID, a DOI or DOI URL, or an OpenAlex ID."""
    s = identifier.strip()
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", s, re.I) or re.fullmatch(
        r"(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?", s, re.I
    )
    if m:
        return f"doi:10.48550/arXiv.{m.group(1)}"
    m = re.search(r"(10\.\d{4,9}/\S+)", s)
    if m:
        return f"doi:{m.group(1)}"
    m = re.search(r"(W\d+)$", s)
    if m:
        return m.group(1)
    raise ValueError(f"Cannot interpret {identifier!r} as an arXiv ID, DOI or OpenAlex ID")


def abstract_of(work: dict) -> str:
    index = work.get("abstract_inverted_index") or {}
    words = sorted((pos, word) for word, positions in index.items() for pos in positions)
    return " ".join(word for _, word in words)


def arxiv_id_of(work: dict) -> str | None:
    blob = json.dumps(work.get("ids") or {}) + (work.get("doi") or "")
    m = re.search(r"(\d{4}\.\d{4,5})", blob)
    return m.group(1) if m else None


def resolve(identifier: str) -> dict:
    work = _get(f"{API}/works/{to_lookup_key(identifier)}")
    if work is None:
        raise SystemExit(f"OpenAlex has no record of {identifier}")
    return work


def citing_works(work: dict) -> list[dict]:
    out, cursor = [], "*"
    while cursor:
        page = _get(
            f"{API}/works",
            {"filter": f"cites:{short_id(work)}", "per_page": 100, "cursor": cursor, "sort": "publication_date"},
        )
        out.extend(page["results"])
        cursor = page["meta"].get("next_cursor") if page["results"] else None
    return out


def has_fulltext(work: dict) -> bool:
    return bool((work.get("has_content") or {}).get("grobid_xml"))


def fulltext_tei(work: dict) -> bytes | None:
    """GROBID TEI XML for a work, from cache if we already paid for it."""
    path = CACHE / "tei" / f"{short_id(work)}.xml"
    if path.exists():
        return path.read_bytes()
    if not has_fulltext(work):
        return None
    xml = _get(f"{CONTENT}/works/{short_id(work)}.grobid-xml", raw=True)
    if xml:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(xml)
    return xml


def uncached_fulltext_count(works: list[dict]) -> int:
    return sum(1 for w in works if has_fulltext(w) and not (CACHE / "tei" / f"{short_id(w)}.xml").exists())
