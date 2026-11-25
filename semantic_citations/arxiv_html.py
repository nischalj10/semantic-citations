"""Find every place a citing paper mentions the target paper, from arXiv's HTML.

arXiv renders papers with LaTeXML, so citations are real links into the
reference list:

    <cite class="ltx_cite">(Gu et al., <a href="#bib.bib12" class="ltx_ref">2025</a>)</cite>
    <li id="bib.bib12" class="ltx_bibitem"> ... Clinical-R1: Empowering ... </li>

This is a line-for-line port of worker/src/arxiv.js, which is written for a
Worker's small CPU budget: it never parses the document, it finds the target's
reference entry, jumps to each link that points at it, and only looks closely
at the paragraph around each one. Keep the two files in step;
`node worker/test/parity.mjs` checks that they produce identical output.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

OPEN, CLOSE = "<TARGET>", "</TARGET>"

# Private markers that survive tag stripping; swapped for OPEN/CLOSE at the end.
S_OPEN, S_CLOSE = "\u0001", "\u0002"
S_COUNT = "\u0003"  # \u0003<n>\u0003 after a target: other works in the same bracket

ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ", "ndash": "–", "mdash": "—", "hellip": "…"}
ABBREVIATIONS = set("al fig figs eq eqs sec secs tab vs cf etc resp no vol dr prof mr ms mrs st approx ref refs pp ca viz inc ltd jr sr".split(" "))


@dataclass
class Target:
    """What we know about the cited paper, used to recognise it."""

    title: str
    arxiv_id: str | None = None
    doi: str | None = None


@dataclass
class Context:
    match: str  # linked | name
    section: str
    sentence: str  # target wrapped in <TARGET>...</TARGET>
    before: str = ""
    after: str = ""
    co_cited: int = 0  # other works cited in the same bracket
    in_float: bool = False  # table row or figure caption
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _decode(s: str) -> str:
    def one(m: re.Match) -> str:
        e = m.group(1)
        if e[0] == "#":
            code = int(e[2:], 16) if e[1] == "x" else int(e[1:], 10)
            return chr(code) if 0 < code < 0x110000 else m.group(0)
        return ENTITIES.get(e, m.group(0))

    return re.sub(r"&(#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z]+);", one, s)


def _to_text(fragment: str) -> str:
    """Text of an HTML fragment: maths as its LaTeX source, cells and breaks as spaces."""
    s = re.sub(r'<math\b[^>]*?\balttext="([^"]*)"[^>]*>[\s\S]*?</math>', lambda m: m.group(1), fragment)
    s = re.sub(r"<math\b[\s\S]*?</math>", "", s)
    s = re.sub(r"</(?:td|th|p|div|li|figcaption)>|<br\b[^>]*>", " ", s)
    s = re.sub(r"<[^>]*>", "", s)
    return re.sub(r"\s+", " ", _decode(s)).strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _unmark(s: str) -> str:
    return re.sub(r"[\u0001\u0002]", "", re.sub(r"\u0003[0-9]+\u0003", "", s))


def _last_index(hay: str, sub: str, frm: int) -> int:
    """JavaScript's lastIndexOf(sub, frm): last occurrence starting at or before frm."""
    return hay.rfind(sub, 0, max(frm, 0) + len(sub))


def _bigrams(a: str) -> dict[str, int]:
    grams: dict[str, int] = {}
    for i in range(len(a) - 1):
        grams[a[i : i + 2]] = grams.get(a[i : i + 2], 0) + 1
    return grams


def _similarity(a: str, grams: dict[str, int], b: str) -> float:
    """Dice coefficient on character bigrams; `grams` is _bigrams(a)."""
    if a == b:
        return 1.0
    if len(a) < 2 or len(b) < 2 or len(b) < len(a) * 0.6 or len(b) > len(a) * 1.6:
        return 0.0
    seen: dict[str, int] = {}
    hits = 0
    for i in range(len(b) - 1):
        g = b[i : i + 2]
        used = seen.get(g, 0)
        if used < grams.get(g, 0):
            seen[g] = used + 1
            hits += 1
    return (2 * hits) / (len(a) + len(b) - 2)


def short_name(title: str) -> str | None:
    """'Clinical-R1' from 'Clinical-R1: Empowering ...', if it looks coined."""
    head = title.split(":")[0].strip()
    if head == title.strip() or len(head.split()) > 3:
        return None
    coined = bool(re.search(r"[0-9]", head)) or bool(re.search(r"[a-z][A-Z]", head)) or "-" in head
    return head if coined and len(head) >= 4 and "$" not in head else None


def find_bib_entries(html: str, target: Target) -> dict | None:
    """Where the reference list sits, and the ids of the target's entries in it.
    Usually one id; two when a paper lists both the preprint and the published version."""
    marker = html.find("ltx_bibliography")
    if marker < 0:
        return None
    start = _last_index(html, "<section", marker)
    end = html.find("</section>", marker)
    if start < 0:
        return None
    if end < 0:
        end = len(html)
    listing = html[start:end]

    want = _norm(target.title)
    want_grams = _bigrams(want)
    doi = target.doi.lower() if target.doi else None
    items = []
    for m in re.finditer(r"<li\b([^>]*)>([\s\S]*?)</li>", listing):
        if "ltx_bibitem" not in m.group(1):
            continue
        ident = re.search(r'\bid="([^"]+)"', m.group(1))
        if ident:
            items.append({"id": ident.group(1), "inner": m.group(2), "text": None})
    # Exact evidence first: the arXiv ID, the DOI, or the full title.
    ids = []
    for item in items:
        item["text"] = _to_text(item["inner"])
        if (target.arxiv_id and target.arxiv_id in item["inner"]) or (doi and doi in item["inner"].lower()) or want in _norm(item["text"]):
            ids.append(item["id"])
    if ids:
        return {"ids": ids, "start": start, "end": end}
    # Otherwise the closest title, if it is close enough.
    best, best_score = None, 0.0
    for item in items:
        for piece in item["text"].split(". "):
            score = _similarity(want, want_grams, _norm(piece))
            if score > best_score:
                best, best_score = item["id"], score
    if best is None or best_score < 0.85:
        return None
    return {"ids": [best], "start": start, "end": end}


def _wrap(text: str) -> str:
    """Put the markers tightly around a citation, outside its brackets and separators."""
    m = re.fullmatch(r"([\[\(\s,;]*)([\s\S]*?)([\]\)\s,;]*)", text)
    lead, core, trail = m.groups() if m else ("", text, "")
    return lead + S_OPEN + core + S_CLOSE + trail if core else text


def _render_cite(inner: str, needles: list[str]) -> str:
    """Text of one <cite>, with the target marked if it is in there."""
    hits = lambda s: any(n in s for n in needles)
    if not hits(inner):
        return _to_text(inner)
    others: set[str] = set()
    # "[12]" is a numbered citation. "(Gu et al., 2025)" is author-year even when
    # only the year is the link, which shows as letters outside the links.
    authors_outside = bool(re.search(r"[A-Za-z]", _to_text(re.sub(r"<a\b[^>]*>[\s\S]*?</a>", "", inner))))
    state = {"numeric": True}

    def anchor(m: re.Match) -> str:
        attrs, text = m.group(1), _to_text(m.group(2))
        if hits(attrs):
            year = bool(re.fullmatch(r"(?:19|20)[0-9]{2}[a-z]?", text))
            if not re.fullmatch(r"[0-9]+[a-z]?", text) or (year and authors_outside):
                state["numeric"] = False
            return S_OPEN + text + S_CLOSE
        href = re.search(r'href="#([^"]+)"', attrs)
        if href:
            others.add(href.group(1))
        return text

    s = _to_text(re.sub(r"<a\b([^>]*)>([\s\S]*?)</a>", anchor, inner))
    if not state["numeric"]:
        # Author-year: the link is often only the year, so mark the whole "Gu et al., 2025".
        s = ";".join(_wrap(_unmark(part)) if S_OPEN in part else part for part in s.split(";"))
    # Attach the co-citation count to the last marker in this bracket.
    last = s.rfind(S_CLOSE)
    return s[: last + 1] + S_COUNT + str(len(others)) + S_COUNT + s[last + 1 :]


def split_sentences(text: str) -> list[str]:
    """Split running text into sentences. Deliberately simple; the JS version must agree."""
    out = []
    start = 0
    for m in re.finditer(r"[.!?]+[\"'”’)\]]*\s+", text):
        end = m.end()
        if end >= len(text):
            break
        if not re.match(r"[A-Z0-9\[(\"“‘\u0001\\]", text[end]):
            continue
        piece = text[start : m.start()]
        if piece.count(S_OPEN) > piece.count(S_CLOSE):
            continue  # inside a marked citation
        if text[m.start()] == ".":
            word = re.search(r"([A-Za-z][A-Za-z.]*)\Z", piece[-24:])
            if word:
                w = word.group(1).lower()
                if len(w) == 1 or "." in w or w in ABBREVIATIONS:
                    continue
        out.append(text[start:end].strip())
        start = end
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return out


def _window(sentence: str, limit: int) -> str:
    """Trim a runaway sentence (usually a table row) around the target."""
    if len(sentence) <= limit:
        return sentence
    start = sentence.find(OPEN)
    end = sentence.find(CLOSE) + len(CLOSE)
    half = max(0, (limit - (end - start)) // 2)
    lo = max(0, start - half)
    hi = min(len(sentence), end + half)
    if lo > 0:
        i = sentence[lo:start].find(" ")
        if i >= 0:
            lo = lo + i + 1
    if hi < len(sentence):
        r = _last_index(sentence, " ", hi - 1)
        if r > end:
            hi = r
    return ("… " if lo > 0 else "") + sentence[lo:hi].strip() + (" …" if hi < len(sentence) else "")


def _clip(value: str, limit: int, keep: str) -> str:
    if len(value) <= limit:
        return value
    if keep == "end":
        tail = value[-limit:]
        i = tail.find(" ")
        return "… " + (tail[i + 1 :] if i >= 0 else tail)
    head = value[:limit]
    i = head.rfind(" ")
    return (head[:i] if i >= 0 else head) + " …"


def _last_open(html: str, tag: str, frm: int) -> int:
    """Index of the nearest `<tag ...>` opening at or before `frm`, or -1."""
    i = frm
    while i >= 0:
        i = _last_index(html, "<" + tag, i)
        if i < 0:
            return -1
        j = i + len(tag) + 1
        if j < len(html) and html[j] in " >\n\t":
            return i
        i -= 1
    return -1


def _block_at(html: str, pos: int) -> dict | None:
    """The paragraph, caption or table row that contains position `pos`."""
    found = None
    for tag in ("tr", "p", "figcaption"):
        open_ = _last_open(html, tag, pos)
        if open_ < 0:
            continue
        close = html.find("</" + tag + ">", open_)
        if close < pos:
            continue  # that element ended before us
        if tag == "tr":
            return {"tag": tag, "open": open_, "close": close}  # a table row beats the cell paragraph inside it
        if found is None or open_ > found["open"]:
            found = {"tag": tag, "open": open_, "close": close}
    if found:
        return found
    open_ = _last_open(html, "div", pos)
    close = html.find("</div>", pos)
    return {"tag": "div", "open": open_, "close": close} if open_ >= 0 and close >= 0 else None


def _section_at(html: str, pos: int) -> str:
    """Nearest section heading above `pos`, e.g. "2 Related Work"."""
    i = pos
    for _ in range(500):
        i = _last_index(html, "<h", i - 1)
        if i < 0:
            return ""
        m = re.match(r"<h[1-6]\b([^>]*)>([\s\S]*?)</h[1-6]>", html[i : i + 4000])
        if m and re.search(r"ltx_title_(?:section|subsection|subsubsection|paragraph|subparagraph|appendix|abstract)", m.group(1)):
            return _to_text(m.group(2))
    return ""


def extract_contexts(html: str, target: Target) -> tuple[dict | None, list[Context]]:
    bib = find_bib_entries(html, target)
    if not bib:
        return None, []
    needles = [f'href="#{ident}"' for ident in bib["ids"]]

    # Every block that links to the target, or names it, keyed by where it starts.
    blocks: dict[int, dict] = {}

    def note(pos: int) -> None:
        if bib["start"] <= pos < bib["end"]:
            return
        block = _block_at(html, pos)
        if block and block["open"] not in blocks:
            blocks[block["open"]] = block

    for needle in needles:
        i = html.find(needle)
        while i >= 0:
            note(i)
            i = html.find(needle, i + 1)

    short = short_name(target.title)
    name_re = re.compile("(?<![A-Za-z0-9_-])" + re.escape(short) + "(?![A-Za-z0-9_])", re.I) if short else None
    if short:
        for variant in dict.fromkeys([short, short.lower(), short.upper()]):
            i = html.find(variant)
            while i >= 0:
                if not _last_index(html, "<", i) > _last_index(html, ">", i):  # not inside a tag's attributes
                    note(i)
                i = html.find(variant, i + 1)

    contexts: list[Context] = []
    for open_ in sorted(blocks):
        block = blocks[open_]
        inner = html[html.find(">", open_) + 1 : block["close"]]
        inner = re.sub(r"<cite\b[^>]*>([\s\S]*?)</cite>", lambda m: _render_cite(m.group(1), needles), inner)
        # A bare link to the target outside any <cite>.
        inner = re.sub(
            r"<a\b([^>]*)>([\s\S]*?)</a>",
            lambda m: S_OPEN + _to_text(m.group(2)) + S_CLOSE if any(n in m.group(1) for n in needles) else m.group(0),
            inner,
        )
        text = _to_text(inner)
        sentences = [text] if block["tag"] == "tr" else split_sentences(text)
        section = _section_at(html, open_)

        for n, raw in enumerate(sentences):
            match = None
            sentence = raw
            co_cited = 0
            if S_OPEN in raw:
                match = "linked"
                for m in re.finditer(r"\u0003([0-9]+)\u0003", raw):
                    co_cited = max(co_cited, int(m.group(1)))
                sentence = re.sub(r"\u0003[0-9]+\u0003", "", raw).replace(S_OPEN, OPEN).replace(S_CLOSE, CLOSE)
            elif name_re and name_re.search(raw):
                match = "name"
                sentence = name_re.sub(lambda m: OPEN + m.group(0) + CLOSE, raw)
            if not match:
                continue
            notes = []
            if len(sentence) > 600:
                notes.append("sentence trimmed around the target; probably a table row or list")
            contexts.append(
                Context(
                    match=match,
                    section=section,
                    sentence=_window(sentence, 600),
                    before=_clip(_unmark(sentences[n - 1]), 400, "end") if n > 0 else "",
                    after=_clip(_unmark(sentences[n + 1]), 400, "start") if n < len(sentences) - 1 else "",
                    co_cited=co_cited,
                    in_float=block["tag"] in ("tr", "figcaption"),
                    notes=notes,
                )
            )
    return {"ids": bib["ids"]}, contexts
