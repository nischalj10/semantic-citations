"""Find every place a citing paper mentions the target paper.

Input is GROBID TEI XML (OpenAlex serves it for most open-access works).
Output is a list of citation contexts: the sentence that cites the target,
its neighbours, the section heading, and how many other works are cited in
the same bracket.

GROBID links most in-text citations to their bibliography entry, but not all
of them, so matching runs in three passes, each only looking at sentences
the previous pass did not claim:

  1. linked   - <ref type="bibr" target="#bN"> pointing at the target entry
  2. marker   - an unlinked <ref> or bare text whose marker matches the
                target ("[13]", "13;14;15", "Gu et al., 2025")
  3. name     - the target's coined short name ("Clinical-R1") in running
                text, which is where results comparisons usually live
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

OPEN, CLOSE = "<TARGET>", "</TARGET>"
BLOCK_TAGS = {TEI + t for t in ("s", "p", "figDesc", "cell", "note", "head", "item")}
SKIP_TAGS = {TEI + "listBibl", TEI + "teiHeader"}


@dataclass
class Target:
    """What we know about the cited paper, used to recognise it."""

    title: str
    arxiv_id: str | None = None
    doi: str | None = None

    @property
    def short_name(self) -> str | None:
        """'Clinical-R1' from 'Clinical-R1: Empowering ...', if it looks coined."""
        head = self.title.split(":")[0].strip()
        if head == self.title.strip() or len(head.split()) > 3:
            return None
        coined = re.search(r"\d", head) or re.search(r"[a-z][A-Z]", head) or "-" in head
        return head if coined and len(head) >= 4 else None


@dataclass
class BibEntry:
    xml_id: str
    number: int  # 1-based position in the reference list
    title: str
    surname: str | None
    year: str | None
    ambiguous_author_year: bool = False


@dataclass
class Context:
    match: str  # linked | marker | name
    section: str
    sentence: str  # target wrapped in <TARGET>...</TARGET>
    before: str = ""
    after: str = ""
    co_cited: int = 0  # other works cited in the same bracket
    in_float: bool = False  # table cell or figure caption
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _text(el: ET.Element) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def find_bib_entry(root: ET.Element, target: Target) -> BibEntry | None:
    entries = root.findall(f".//{TEI}listBibl/{TEI}biblStruct")
    want = _norm(target.title)
    best, best_score = None, 0.0
    for i, bib in enumerate(entries):
        raw = _text(bib)
        titles = [_text(t) for t in bib.iter(TEI + "title")]
        score = max((SequenceMatcher(None, want, _norm(t)).ratio() for t in titles), default=0.0)
        if target.arxiv_id and target.arxiv_id in raw:
            score = 1.0
        if target.doi and target.doi.lower() in raw.lower():
            score = 1.0
        if score > best_score:
            best, best_score = (i, bib, titles), score
    if best is None or best_score < 0.85:
        return None

    i, bib, titles = best
    surname_el = bib.find(f".//{TEI}author/{TEI}persName/{TEI}surname")
    date_el = bib.find(f".//{TEI}date")
    year = None
    if date_el is not None:
        m = re.search(r"(19|20)\d{2}", date_el.get("when") or _text(date_el))
        year = m.group(0) if m else None
    surname = _text(surname_el) if surname_el is not None else None

    # "Gu et al., 2025" is ambiguous if another entry shares surname and year.
    ambiguous = False
    if surname:
        for j, other in enumerate(entries):
            if j == i:
                continue
            s = other.find(f".//{TEI}author/{TEI}persName/{TEI}surname")
            d = other.find(f".//{TEI}date")
            oy = re.search(r"(19|20)\d{2}", (d.get("when") or _text(d)) if d is not None else "")
            if s is not None and _text(s) == surname and oy and year and oy.group(0)[:4] == year:
                ambiguous = True
    return BibEntry(
        xml_id=bib.get(XML_ID) or f"b{i}",
        number=i + 1,
        title=max(titles, key=len) if titles else "",
        surname=surname,
        year=year,
        ambiguous_author_year=ambiguous,
    )


def _expand_numbers(marker: str) -> list[int]:
    """'13;14-16, 20' -> [13, 14, 15, 16, 20]. Empty if not a numeric marker."""
    core = marker.strip("[]()  ")
    if not re.fullmatch(r"[\d\s,;–—-]+", core) or not re.search(r"\d", core):
        return []
    out: list[int] = []
    for part in re.split(r"[,;]", core):
        part = part.strip()
        m = re.fullmatch(r"(\d+)\s*[–—-]\s*(\d+)", part)
        if m and 0 < int(m.group(2)) - int(m.group(1)) < 60:
            out.extend(range(int(m.group(1)), int(m.group(2)) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def _wrap(marker: str) -> str:
    """Put the TARGET tags tightly around the marker, outside its punctuation."""
    m = re.fullmatch(r"([\[\(\s,;]*)(.*?)([\]\)\s,;]*)", marker, re.S)
    lead, core, trail = m.groups() if m else ("", marker, "")
    return f"{lead}{OPEN}{core}{CLOSE}{trail}" if core else marker


def _window(sentence: str, limit: int = 600) -> str:
    """Trim a runaway sentence (usually a flattened table) around the target."""
    if len(sentence) <= limit:
        return sentence
    start, end = sentence.find(OPEN), sentence.find(CLOSE) + len(CLOSE)
    half = max(0, (limit - (end - start)) // 2)
    lo, hi = max(0, start - half), min(len(sentence), end + half)
    if lo > 0:
        lo = sentence.find(" ", lo, start) + 1 or lo
    if hi < len(sentence):
        hi = sentence.rfind(" ", end, hi) if sentence.rfind(" ", end, hi) > end else hi
    return ("\u2026 " if lo > 0 else "") + sentence[lo:hi].strip() + (" \u2026" if hi < len(sentence) else "")


def _clip(text: str, limit: int, keep: str) -> str:
    if len(text) <= limit:
        return text
    if keep == "end":
        return "\u2026 " + text[-limit:].split(" ", 1)[-1]
    return text[:limit].rsplit(" ", 1)[0] + " \u2026"


class _Doc:
    def __init__(self, root: ET.Element, target: Target, bib: BibEntry):
        self.root, self.target, self.bib = root, target, bib
        self.parent = {c: p for p in root.iter() for c in p}
        refs = [r for r in root.iter(TEI + "ref") if r.get("type") == "bibr"]
        linked = [r for r in refs if r.get("target")]
        numeric = sum(1 for r in linked if _expand_numbers(r.text or ""))
        self.numeric_style = bool(linked) and numeric / len(linked) > 0.5
        if not linked:
            self.numeric_style = sum(1 for r in refs if _expand_numbers(r.text or "")) > len(refs) / 2
        self.author_year = None
        if bib.surname and bib.year:
            self.author_year = re.compile(
                rf"{re.escape(bib.surname)}(?:\s+et\s+al\.?|\s+and\s+\w+|\s*&\s*\w+)?[\s,]*\(?\s*{bib.year}[a-z]?\b"
            )
        self.name = None
        if target.short_name:
            self.name = re.compile(rf"(?<![\w-]){re.escape(target.short_name)}(?![\w])", re.I)

    # --- structure helpers -------------------------------------------------
    def block_of(self, el: ET.Element) -> ET.Element | None:
        while el is not None:
            if el.tag in BLOCK_TAGS:
                return el
            el = self.parent.get(el)
        return None

    def in_skipped(self, el: ET.Element) -> bool:
        while el is not None:
            if el.tag in SKIP_TAGS:
                return True
            el = self.parent.get(el)
        return False

    def in_float(self, el: ET.Element) -> bool:
        while el is not None:
            if el.tag == TEI + "figure":
                return True
            el = self.parent.get(el)
        return False

    def section_of(self, el: ET.Element) -> str:
        while el is not None:
            if el.tag == TEI + "figure":
                head = el.find(TEI + "head")
                return _text(head) if head is not None else "Figure/Table"
            if el.tag == TEI + "div":
                head = el.find(TEI + "head")
                if head is not None:
                    n = head.get("n")
                    return f"{n} {_text(head)}".strip() if n else _text(head)
            if el.tag == TEI + "abstract":
                return "Abstract"
            el = self.parent.get(el)
        return ""

    def neighbours(self, block: ET.Element) -> tuple[str, str]:
        if block.tag != TEI + "s":
            return "", ""
        par = self.parent.get(block)
        sibs = [c for c in par if c.tag == TEI + "s"] if par is not None else []
        i = sibs.index(block) if block in sibs else -1
        before = _text(sibs[i - 1]) if i > 0 else ""
        after = _text(sibs[i + 1]) if 0 <= i < len(sibs) - 1 else ""
        return before, after

    # --- matching ----------------------------------------------------------
    def is_target_ref(self, ref: ET.Element) -> str | None:
        """Return the matching pass that claims this <ref>, or None."""
        if ref.get("target") == "#" + self.bib.xml_id:
            return "linked"
        if ref.get("target"):
            return None
        text = ref.text or ""
        if self.numeric_style and self.bib.number in _expand_numbers(text):
            return "marker"
        if self.author_year and self.author_year.search(text):
            return "marker"
        return None

    def render(self, block: ET.Element) -> tuple[str, list[str], int]:
        """Sentence text with the target wrapped; which passes matched; co-citation count."""
        matches: list[str] = []
        parts: list[str] = [block.text or ""]
        group: list[bool] = []  # is_target flags for the current run of adjacent refs
        best_group = 0

        def close_group():
            nonlocal best_group, group
            if any(group):
                best_group = max(best_group, len(group) - 1)
            group = []

        for child in block:
            if child.tag == TEI + "ref" and child.get("type") == "bibr":
                how = self.is_target_ref(child)
                text = "".join(child.itertext())
                nums = _expand_numbers(text)
                if how:
                    matches.append(how)
                    if len(nums) > 1:  # "13;14;15" in a single unlinked ref
                        text = re.sub(rf"(?<!\d){self.bib.number}(?!\d)", f"{OPEN}{self.bib.number}{CLOSE}", text, count=1)
                        if OPEN not in text:  # target sits inside a range like 10-14
                            text = _wrap(text)
                        group.extend([True] + [False] * (len(nums) - 1))
                    else:
                        text = _wrap(text)
                        group.append(True)
                else:
                    group.extend([False] * max(1, len(nums)))
                parts.append(text)
                tail = child.tail or ""
                if re.fullmatch(r"[\s,;]*", tail) is None:
                    close_group()
            else:
                close_group()
                parts.append("".join(child.itertext()))
            parts.append(child.tail or "")
        close_group()
        return re.sub(r"\s+", " ", "".join(parts)).strip(), matches, best_group


def extract_contexts(tei_xml: bytes | str, target: Target) -> tuple[BibEntry | None, list[Context]]:
    root = ET.fromstring(tei_xml)
    bib = find_bib_entry(root, target)
    if bib is None:
        return None, []
    doc = _Doc(root, target, bib)

    blocks: list[ET.Element] = []
    seen: set[int] = set()
    for el in root.iter():
        if el.tag in BLOCK_TAGS and not doc.in_skipped(el):
            # keep the innermost block only (an <s> inside a <p>, not the <p>)
            if any(c.tag in BLOCK_TAGS for c in el.iter() if c is not el):
                continue
            if id(el) not in seen:
                seen.add(id(el))
                blocks.append(el)

    contexts: list[Context] = []
    for block in blocks:
        sentence, matches, co_cited = doc.render(block)
        notes: list[str] = []
        how = None
        if "linked" in matches:
            how = "linked"
        elif "marker" in matches:
            how = "marker"
        elif doc.author_year and doc.author_year.search(sentence):
            # bare-text marker GROBID did not tag as a reference at all
            how = "marker"
            sentence = doc.author_year.sub(lambda m: f"{OPEN}{m.group(0)}{CLOSE}", sentence, count=1)
        elif doc.name and doc.name.search(sentence):
            how = "name"
            sentence = doc.name.sub(lambda m: f"{OPEN}{m.group(0)}{CLOSE}", sentence)
        if how is None:
            continue
        if how == "marker" and not doc.numeric_style and bib.ambiguous_author_year:
            notes.append("author-year marker is shared by another reference")
        if how == "marker":
            notes.append("matched by marker text; GROBID did not link this citation")
        before, after = doc.neighbours(block)
        if len(sentence) > 600:
            notes.append("sentence trimmed around the target; probably a flattened table or list")
        sentence = _window(sentence)
        before, after = _clip(before, 400, "end"), _clip(after, 400, "start")
        contexts.append(
            Context(
                match=how,
                section=doc.section_of(block),
                sentence=sentence,
                before=before,
                after=after,
                co_cited=co_cited,
                in_float=doc.in_float(block),
                notes=notes,
            )
        )
    return bib, contexts
