// Find every place a citing paper mentions the target paper, from arXiv's HTML.
//
// arXiv renders papers with LaTeXML, so citations are real links into the
// reference list:
//
//   <cite class="ltx_cite">(Gu et al., <a href="#bib.bib12" class="ltx_ref">2025</a>)</cite>
//   <li id="bib.bib12" class="ltx_bibitem"> ... Clinical-R1: Empowering ... </li>
//
// Pages run to several megabytes of MathML, and a Worker has a small CPU
// budget, so this never parses the document. It finds the target's reference
// entry, jumps to each link that points at it with indexOf, and only looks
// closely at the paragraph around each one.
//
// semantic_citations/arxiv_html.py is a line-for-line port; worker/test/parity.mjs
// checks that both produce identical output.

export const OPEN = "<TARGET>";
export const CLOSE = "</TARGET>";

// Private markers that survive tag stripping; swapped for OPEN/CLOSE at the end.
const S_OPEN = "\u0001";
const S_CLOSE = "\u0002";
const S_COUNT = "\u0003"; // \u0003<n>\u0003 after a target: other works in the same bracket

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", ndash: "–", mdash: "—", hellip: "…" };
const ABBREVIATIONS = new Set(
  "al fig figs eq eqs sec secs tab vs cf etc resp no vol dr prof mr ms mrs st approx ref refs pp ca viz inc ltd jr sr".split(" "),
);

function decode(s) {
  return s.replace(/&(#x[0-9a-fA-F]+|#[0-9]+|[A-Za-z]+);/g, (m, e) => {
    if (e[0] === "#") {
      const code = e[1] === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return code > 0 && code < 0x110000 ? String.fromCodePoint(code) : m;
    }
    return Object.prototype.hasOwnProperty.call(ENTITIES, e) ? ENTITIES[e] : m;
  });
}

/** Text of an HTML fragment: maths as its LaTeX source, cells and breaks as spaces. */
function toText(fragment) {
  let s = fragment.replace(/<math\b[^>]*?\balttext="([^"]*)"[^>]*>[\s\S]*?<\/math>/g, (m, alt) => alt);
  s = s.replace(/<math\b[\s\S]*?<\/math>/g, "");
  s = s.replace(/<\/(?:td|th|p|div|li|figcaption)>|<br\b[^>]*>/g, " ");
  s = s.replace(/<[^>]*>/g, "");
  return decode(s).replace(/\s+/g, " ").trim();
}

const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const unmark = (s) => s.replace(/\u0003[0-9]+\u0003/g, "").replace(/[\u0001\u0002]/g, "");

function bigrams(a) {
  const grams = new Map();
  for (let i = 0; i < a.length - 1; i++) grams.set(a.slice(i, i + 2), (grams.get(a.slice(i, i + 2)) || 0) + 1);
  return grams;
}

/** Dice coefficient on character bigrams; `grams` is bigrams(a). */
function similarity(a, grams, b) {
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2 || b.length < a.length * 0.6 || b.length > a.length * 1.6) return 0;
  const seen = new Map();
  let hits = 0;
  for (let i = 0; i < b.length - 1; i++) {
    const g = b.slice(i, i + 2);
    const used = seen.get(g) || 0;
    if (used < (grams.get(g) || 0)) {
      seen.set(g, used + 1);
      hits++;
    }
  }
  return (2 * hits) / (a.length + b.length - 2);
}

/** 'Clinical-R1' from 'Clinical-R1: Empowering ...', if it looks coined. */
export function shortName(title) {
  const head = title.split(":")[0].trim();
  if (head === title.trim() || head.split(/\s+/).length > 3) return null;
  const coined = /[0-9]/.test(head) || /[a-z][A-Z]/.test(head) || head.includes("-");
  return coined && head.length >= 4 && !head.includes("$") ? head : null;
}

/**
 * Where the reference list sits, and the ids of the target's entries in it.
 * Usually one id; two when a paper lists both the preprint and the published version.
 */
export function findBibEntries(html, target) {
  const marker = html.indexOf("ltx_bibliography");
  if (marker < 0) return null;
  const start = html.lastIndexOf("<section", marker);
  let end = html.indexOf("</section>", marker);
  if (start < 0) return null;
  if (end < 0) end = html.length;
  const list = html.slice(start, end);

  const want = norm(target.title);
  const wantGrams = bigrams(want);
  const doi = target.doi ? target.doi.toLowerCase() : null;
  const items = [];
  for (const m of list.matchAll(/<li\b([^>]*)>([\s\S]*?)<\/li>/g)) {
    if (!m[1].includes("ltx_bibitem")) continue;
    const id = /\bid="([^"]+)"/.exec(m[1]);
    if (id) items.push({ id: id[1], inner: m[2], text: null });
  }
  // Exact evidence first: the arXiv ID, the DOI, or the full title.
  const ids = [];
  for (const item of items) {
    item.text = toText(item.inner);
    if (
      (target.arxivId && item.inner.includes(target.arxivId)) ||
      (doi && item.inner.toLowerCase().includes(doi)) ||
      norm(item.text).includes(want)
    ) {
      ids.push(item.id);
    }
  }
  if (ids.length) return { ids, start, end };
  // Otherwise the closest title, if it is close enough.
  let best = null;
  let bestScore = 0;
  for (const item of items) {
    for (const piece of item.text.split(". ")) {
      const score = similarity(want, wantGrams, norm(piece));
      if (score > bestScore) {
        best = item.id;
        bestScore = score;
      }
    }
  }
  if (best === null || bestScore < 0.85) return null;
  return { ids: [best], start, end };
}

/** Put the markers tightly around a citation, outside its brackets and separators. */
function wrap(text) {
  const m = /^([\[\(\s,;]*)([\s\S]*?)([\]\)\s,;]*)$/.exec(text);
  const lead = m ? m[1] : "";
  const core = m ? m[2] : text;
  const trail = m ? m[3] : "";
  return core ? lead + S_OPEN + core + S_CLOSE + trail : text;
}

/** Text of one <cite>, with the target marked if it is in there. */
function renderCite(inner, needles) {
  const hits = (s) => needles.some((n) => s.includes(n));
  if (!hits(inner)) return toText(inner);
  const others = new Set();
  // "[12]" is a numbered citation. "(Gu et al., 2025)" is author-year even when
  // only the year is the link, which shows as letters outside the links.
  const authorsOutside = /[A-Za-z]/.test(toText(inner.replace(/<a\b[^>]*>[\s\S]*?<\/a>/g, "")));
  let numeric = true;
  let s = inner.replace(/<a\b([^>]*)>([\s\S]*?)<\/a>/g, (m, attrs, label) => {
    const text = toText(label);
    if (hits(attrs)) {
      const year = /^(?:19|20)[0-9]{2}[a-z]?$/.test(text);
      if (!/^[0-9]+[a-z]?$/.test(text) || (year && authorsOutside)) numeric = false;
      return S_OPEN + text + S_CLOSE;
    }
    const href = /href="#([^"]+)"/.exec(attrs);
    if (href) others.add(href[1]);
    return text;
  });
  s = toText(s);
  if (!numeric) {
    // Author-year: the link is often only the year, so mark the whole "Gu et al., 2025".
    s = s
      .split(";")
      .map((part) => (part.includes(S_OPEN) ? wrap(unmark(part)) : part))
      .join(";");
  }
  // Attach the co-citation count to the last marker in this bracket.
  const last = s.lastIndexOf(S_CLOSE);
  return s.slice(0, last + 1) + S_COUNT + others.size + S_COUNT + s.slice(last + 1);
}

/** Split running text into sentences. Deliberately simple; the Python port must agree. */
export function splitSentences(text) {
  const out = [];
  const re = /[.!?]+["'”’)\]]*\s+/g;
  let start = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    const end = m.index + m[0].length;
    if (end >= text.length) break;
    if (!/[A-Z0-9\[("“‘\u0001\\]/.test(text[end])) continue;
    const piece = text.slice(start, m.index);
    if (piece.split(S_OPEN).length > piece.split(S_CLOSE).length) continue; // inside a marked citation
    if (text[m.index] === ".") {
      const word = /([A-Za-z][A-Za-z.]*)$/.exec(piece.slice(-24));
      if (word) {
        const w = word[1].toLowerCase();
        if (w.length === 1 || w.includes(".") || ABBREVIATIONS.has(w)) continue;
      }
    }
    out.push(text.slice(start, end).trim());
    start = end;
  }
  const rest = text.slice(start).trim();
  if (rest) out.push(rest);
  return out;
}

/** Trim a runaway sentence (usually a table row) around the target. */
function windowAround(sentence, limit) {
  if (sentence.length <= limit) return sentence;
  const start = sentence.indexOf(OPEN);
  const end = sentence.indexOf(CLOSE) + CLOSE.length;
  const half = Math.max(0, Math.floor((limit - (end - start)) / 2));
  let lo = Math.max(0, start - half);
  let hi = Math.min(sentence.length, end + half);
  if (lo > 0) {
    const i = sentence.slice(lo, start).indexOf(" ");
    if (i >= 0) lo = lo + i + 1;
  }
  if (hi < sentence.length) {
    const r = sentence.lastIndexOf(" ", hi - 1);
    if (r > end) hi = r;
  }
  return (lo > 0 ? "… " : "") + sentence.slice(lo, hi).trim() + (hi < sentence.length ? " …" : "");
}

function clip(value, limit, keep) {
  if (value.length <= limit) return value;
  if (keep === "end") {
    const tail = value.slice(-limit);
    const i = tail.indexOf(" ");
    return "… " + (i >= 0 ? tail.slice(i + 1) : tail);
  }
  const head = value.slice(0, limit);
  const i = head.lastIndexOf(" ");
  return (i >= 0 ? head.slice(0, i) : head) + " …";
}

/** Index of the nearest `<tag ...>` opening at or before `from`, or -1. */
function lastOpen(html, tag, from) {
  let i = from;
  while (i >= 0) {
    i = html.lastIndexOf("<" + tag, i);
    if (i < 0) return -1;
    const next = html[i + tag.length + 1];
    if (next === " " || next === ">" || next === "\n" || next === "\t") return i;
    i -= 1;
  }
  return -1;
}

/** The paragraph, caption or table row that contains position `pos`. */
function blockAt(html, pos) {
  let found = null;
  for (const tag of ["tr", "p", "figcaption"]) {
    const open = lastOpen(html, tag, pos);
    if (open < 0) continue;
    const close = html.indexOf("</" + tag + ">", open);
    if (close < pos) continue; // that element ended before us
    if (tag === "tr") return { tag, open, close }; // a table row beats the cell paragraph inside it
    if (found === null || open > found.open) found = { tag, open, close };
  }
  if (found) return found;
  const open = lastOpen(html, "div", pos);
  const close = html.indexOf("</div>", pos);
  return open >= 0 && close >= 0 ? { tag: "div", open, close } : null;
}

/** Nearest section heading above `pos`, e.g. "2 Related Work". */
function sectionAt(html, pos) {
  let i = pos;
  for (let guard = 0; guard < 500; guard++) {
    i = html.lastIndexOf("<h", i - 1);
    if (i < 0) return "";
    const m = /^<h[1-6]\b([^>]*)>([\s\S]*?)<\/h[1-6]>/.exec(html.slice(i, i + 4000));
    if (m && /ltx_title_(?:section|subsection|subsubsection|paragraph|subparagraph|appendix|abstract)/.test(m[1])) return toText(m[2]);
  }
  return "";
}

/**
 * @param {string} html an arXiv (LaTeXML) HTML page
 * @param {{title: string, arxivId?: string|null, doi?: string|null}} target
 * @returns {{bib: {ids: string[]}|null, contexts: object[]}}
 */
export function extractContexts(html, target) {
  const bib = findBibEntries(html, target);
  if (!bib) return { bib: null, contexts: [] };
  const needles = bib.ids.map((id) => `href="#${id}"`);
  const inList = (pos) => pos >= bib.start && pos < bib.end;

  // Every block that links to the target, or names it, keyed by where it starts.
  const blocks = new Map();
  const note = (pos) => {
    if (inList(pos)) return;
    const block = blockAt(html, pos);
    if (block && !blocks.has(block.open)) blocks.set(block.open, block);
  };
  for (const needle of needles) {
    for (let i = html.indexOf(needle); i >= 0; i = html.indexOf(needle, i + 1)) note(i);
  }

  const short = shortName(target.title);
  const nameRe = short ? new RegExp("(?<![A-Za-z0-9_-])" + escapeRe(short) + "(?![A-Za-z0-9_])", "gi") : null;
  if (short) {
    for (const variant of new Set([short, short.toLowerCase(), short.toUpperCase()])) {
      for (let i = html.indexOf(variant); i >= 0; i = html.indexOf(variant, i + 1)) {
        if (html.lastIndexOf("<", i) > html.lastIndexOf(">", i)) continue; // inside a tag's attributes
        note(i);
      }
    }
  }

  const contexts = [];
  for (const open of [...blocks.keys()].sort((a, b) => a - b)) {
    const block = blocks.get(open);
    let inner = html.slice(html.indexOf(">", open) + 1, block.close);
    inner = inner.replace(/<cite\b[^>]*>([\s\S]*?)<\/cite>/g, (m, cite) => renderCite(cite, needles));
    // A bare link to the target outside any <cite>.
    inner = inner.replace(/<a\b([^>]*)>([\s\S]*?)<\/a>/g, (m, attrs, label) => (needles.some((n) => attrs.includes(n)) ? S_OPEN + toText(label) + S_CLOSE : m));
    const text = toText(inner);
    const sentences = block.tag === "tr" ? [text] : splitSentences(text);
    const section = sectionAt(html, open);

    sentences.forEach((raw, i) => {
      let match = null;
      let sentence = raw;
      let coCited = 0;
      if (raw.includes(S_OPEN)) {
        match = "linked";
        for (const m of raw.matchAll(/\u0003([0-9]+)\u0003/g)) coCited = Math.max(coCited, Number(m[1]));
        sentence = raw.replace(/\u0003[0-9]+\u0003/g, "").split(S_OPEN).join(OPEN).split(S_CLOSE).join(CLOSE);
      } else if (nameRe && ((nameRe.lastIndex = 0), nameRe.test(raw))) {
        match = "name";
        sentence = raw.replace(nameRe, (m) => OPEN + m + CLOSE);
      }
      if (!match) return;
      const notes = [];
      if (sentence.length > 600) notes.push("sentence trimmed around the target; probably a table row or list");
      contexts.push({
        match,
        section,
        sentence: windowAround(sentence, 600),
        before: i > 0 ? clip(unmark(sentences[i - 1]), 400, "end") : "",
        after: i < sentences.length - 1 ? clip(unmark(sentences[i + 1]), 400, "start") : "",
        co_cited: coCited,
        in_float: block.tag === "tr" || block.tag === "figcaption",
        notes,
      });
    });
  }
  return { bib: { ids: bib.ids }, contexts };
}
