// Find every place a citing paper mentions the target paper.
//
// A port of semantic_citations/tei.py. The Python version builds an XML tree;
// this one scans the text for the handful of tags it needs, because a Worker
// has a small CPU budget and a survey paper's full text can be 700 KB.
// worker/test/parity.mjs checks that both produce the same contexts.

export const OPEN = "<TARGET>";
export const CLOSE = "</TARGET>";

const BLOCK_TAGS = new Set(["s", "p", "figDesc", "cell", "note", "head", "item"]);
const TAG_RE = /<(\/?)(div|figure|s|p|figDesc|cell|note|head|item)(?=[\s>\/])([^>]*)>/g;
const REF_RE = /<ref\b([^>]*?)(?:\/>|>([\s\S]*?)<\/ref>)/g;
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };

const decode = (s) =>
  s.replace(/&(#x[0-9a-fA-F]+|#\d+|\w+);/g, (m, e) => {
    if (e[0] === "#") return String.fromCodePoint(e[1] === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10));
    return ENTITIES[e] ?? m;
  });
const stripTags = (xml) => decode(xml.replace(/<[^>]*>/g, ""));
const squash = (s) => s.replace(/\s+/g, " ").trim();
const text = (xml) => squash(stripTags(xml));
const norm = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function bigrams(a) {
  const grams = new Map();
  for (let i = 0; i < a.length - 1; i++) grams.set(a.slice(i, i + 2), (grams.get(a.slice(i, i + 2)) || 0) + 1);
  return grams;
}

/** Dice coefficient on character bigrams; `grams` is bigrams(a), computed once by the caller. */
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
  const coined = /\d/.test(head) || /[a-z][A-Z]/.test(head) || head.includes("-");
  return coined && head.length >= 4 ? head : null;
}

function yearOf(entryXml) {
  const date = /<date\b([^>]*?)(?:\/>|>([\s\S]*?)<\/date>)/.exec(entryXml);
  if (!date) return null;
  const when = /when="([^"]*)"/.exec(date[1]);
  const m = /(19|20)\d{2}/.exec((when && when[1]) || text(date[2] || ""));
  return m ? m[0] : null;
}

function surnameOf(entryXml) {
  const m = /<author\b[\s\S]*?<surname[^>]*>([\s\S]*?)<\/surname>/.exec(entryXml);
  return m ? text(m[1]) : null;
}

export function findBibEntry(xml, target) {
  const entries = [];
  for (const list of xml.matchAll(/<listBibl\b[\s\S]*?<\/listBibl>/g)) {
    for (const m of list[0].matchAll(/<biblStruct\b([^>]*)>[\s\S]*?<\/biblStruct>/g)) entries.push(m);
  }
  const want = norm(target.title);
  const wantGrams = bigrams(want);
  const doi = target.doi ? target.doi.toLowerCase() : null;
  let best = -1;
  let bestScore = 0;
  entries.forEach((m, i) => {
    let score = 0;
    for (const t of m[0].matchAll(/<title\b[^>]*>([\s\S]*?)<\/title>/g)) score = Math.max(score, similarity(want, wantGrams, norm(text(t[1]))));
    if (target.arxivId && m[0].includes(target.arxivId)) score = 1;
    if (doi && m[0].toLowerCase().includes(doi)) score = 1;
    if (score > bestScore) {
      best = i;
      bestScore = score;
    }
  });
  if (best < 0 || bestScore < 0.85) return null;

  const entry = entries[best];
  const id = /xml:id="([^"]+)"/.exec(entry[1]);
  const surname = surnameOf(entry[0]);
  const year = yearOf(entry[0]);
  // "Gu et al., 2025" is ambiguous if another entry shares surname and year.
  const ambiguous =
    Boolean(surname && year) && entries.some((m, j) => j !== best && m[0].includes(surname) && surnameOf(m[0]) === surname && yearOf(m[0]) === year);
  return { xmlId: id ? id[1] : `b${best}`, number: best + 1, surname, year, ambiguous };
}

/** '13;14-16, 20' -> [13, 14, 15, 16, 20]. Empty if not a numeric marker. */
export function expandNumbers(marker) {
  const core = marker.replace(/^[\[\]()  ]+|[\[\]()  ]+$/g, "");
  if (!/^[\d\s,;–—-]+$/.test(core) || !/\d/.test(core)) return [];
  const out = [];
  for (let part of core.split(/[,;]/)) {
    part = part.trim();
    const m = /^(\d+)\s*[–—-]\s*(\d+)$/.exec(part);
    if (m && Number(m[2]) - Number(m[1]) > 0 && Number(m[2]) - Number(m[1]) < 60) {
      for (let n = Number(m[1]); n <= Number(m[2]); n++) out.push(n);
    } else if (/^\d+$/.test(part)) {
      out.push(Number(part));
    }
  }
  return out;
}

/** Put the TARGET tags tightly around the marker, outside its punctuation. */
export function wrap(marker) {
  const m = /^([\[\(\s,;]*)([\s\S]*?)([\]\)\s,;]*)$/.exec(marker);
  const [lead, core, trail] = m ? [m[1], m[2], m[3]] : ["", marker, ""];
  return core ? `${lead}${OPEN}${core}${CLOSE}${trail}` : marker;
}

/** Trim a runaway sentence (usually a flattened table) around the target. */
function windowAround(sentence, limit = 600) {
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

/** Innermost text blocks of the body, in order, with their section and siblings. */
function scanBlocks(body) {
  const blocks = [];
  const stack = [];
  let nextId = 0;
  for (const m of body.matchAll(TAG_RE)) {
    const closing = m[1] === "/";
    const tag = m[2];
    if (!closing) {
      if (m[3].endsWith("/")) continue; // self-closing, no content
      if (BLOCK_TAGS.has(tag)) for (const frame of stack) frame.hasBlockChild = true;
      stack.push({ tag, id: nextId++, attrs: m[3], innerStart: m.index + m[0].length, hasBlockChild: false, head: null });
      continue;
    }
    let frame = stack.pop();
    while (frame && frame.tag !== tag) frame = stack.pop(); // tolerate stray tags
    if (!frame || !BLOCK_TAGS.has(tag) || frame.hasBlockChild) continue;

    const inner = body.slice(frame.innerStart, m.index);
    const parent = stack[stack.length - 1];
    if (tag === "head" && parent && (parent.tag === "div" || parent.tag === "figure") && parent.head === null) {
      const n = /\bn="([^"]*)"/.exec(frame.attrs);
      const label = text(inner);
      parent.head = parent.tag === "div" && n ? `${n[1]} ${label}`.trim() : label;
    }
    let section = "";
    let inFloat = false;
    for (let i = stack.length - 1; i >= 0; i--) {
      if (stack[i].tag === "figure") {
        inFloat = true;
        if (!section) section = stack[i].head ?? "Figure/Table";
      } else if (stack[i].tag === "div" && !section && stack[i].head !== null) {
        section = stack[i].head;
      }
    }
    blocks.push({ tag, inner, parentId: parent ? parent.id : -1, section, inFloat });
  }
  return blocks;
}

/**
 * @param {string} xml GROBID TEI
 * @param {{title: string, arxivId?: string|null, doi?: string|null}} target
 * @returns {{bib: object|null, contexts: object[]}}
 */
export function extractContexts(xml, target) {
  const bib = findBibEntry(xml, target);
  if (!bib) return { bib: null, contexts: [] };

  // Is this a numeric-citation paper? Decide from the linked references.
  let linked = 0;
  let linkedNumeric = 0;
  let total = 0;
  let totalNumeric = 0;
  for (const m of xml.matchAll(REF_RE)) {
    if (!/type="bibr"/.test(m[1])) continue;
    const numeric = expandNumbers(stripTags(m[2] || "")).length > 0;
    total++;
    if (numeric) totalNumeric++;
    if (/target="[^"]+"/.test(m[1])) {
      linked++;
      if (numeric) linkedNumeric++;
    }
  }
  const numericStyle = linked > 0 ? linkedNumeric / linked > 0.5 : totalNumeric > total / 2;

  const authorYear =
    bib.surname && bib.year
      ? new RegExp(`${escapeRe(bib.surname)}(?:\\s+et\\s+al\\.?|\\s+and\\s+[\\p{L}\\p{N}_]+|\\s*&\\s*[\\p{L}\\p{N}_]+)?[\\s,]*\\(?\\s*${bib.year}[a-z]?\\b`, "u")
      : null;
  const short = shortName(target.title);
  const nameRe = short ? new RegExp(`(?<![\\w-])${escapeRe(short)}(?!\\w)`, "gi") : null;
  const linkNeedle = `target="#${bib.xmlId}"`;

  const isTargetRef = (attrs, refText) => {
    const t = /target="([^"]*)"/.exec(attrs);
    if (t && t[1] === `#${bib.xmlId}`) return "linked";
    if (t && t[1]) return null;
    if (numericStyle && expandNumbers(refText).includes(bib.number)) return "marker";
    if (authorYear && authorYear.test(refText)) return "marker";
    return null;
  };

  const render = (inner) => {
    const parts = [];
    const matches = [];
    let group = [];
    let best = 0;
    let last = 0;
    let afterBibr = false;
    const closeGroup = () => {
      if (group.some(Boolean)) best = Math.max(best, group.length - 1);
      group = [];
    };
    const gap = (between) => {
      // A run of citations ends at any real text or any other element.
      if (afterBibr && (between.includes("<") || !/^[\s,;]*$/.test(decode(between)))) closeGroup();
      parts.push(stripTags(between));
    };
    for (const m of inner.matchAll(REF_RE)) {
      gap(inner.slice(last, m.index));
      last = m.index + m[0].length;
      let refText = stripTags(m[2] || "");
      if (!/type="bibr"/.test(m[1])) {
        closeGroup();
        afterBibr = false;
        parts.push(refText);
        continue;
      }
      const how = isTargetRef(m[1], refText);
      const nums = expandNumbers(refText);
      if (how) {
        matches.push(how);
        if (nums.length > 1) {
          refText = refText.replace(new RegExp(`(?<!\\d)${bib.number}(?!\\d)`), `${OPEN}${bib.number}${CLOSE}`);
          if (!refText.includes(OPEN)) refText = wrap(refText); // target sits inside a range like 10-14
          group.push(true, ...Array(nums.length - 1).fill(false));
        } else {
          refText = wrap(refText);
          group.push(true);
        }
      } else {
        group.push(...Array(Math.max(1, nums.length)).fill(false));
      }
      parts.push(refText);
      afterBibr = true;
    }
    gap(inner.slice(last));
    closeGroup();
    return { sentence: squash(parts.join("")), matches, coCited: best };
  };

  const headerEnd = xml.indexOf("</teiHeader>");
  const body = (headerEnd >= 0 ? xml.slice(headerEnd) : xml).replace(/<listBibl\b[\s\S]*?<\/listBibl>/g, "");
  const blocks = scanBlocks(body);
  const sentenceSiblings = new Map();
  blocks.forEach((b, i) => {
    if (b.tag !== "s") return;
    if (!sentenceSiblings.has(b.parentId)) sentenceSiblings.set(b.parentId, []);
    sentenceSiblings.get(b.parentId).push(i);
  });

  const contexts = [];
  blocks.forEach((block, index) => {
    const inner = block.inner;
    const mayMatch =
      inner.includes(linkNeedle) ||
      (bib.surname && inner.includes(bib.surname)) ||
      (numericStyle && /<ref\b(?![^>]*\btarget="[^"]+")[^>]*type="bibr"/.test(inner)) ||
      (nameRe && ((nameRe.lastIndex = 0), nameRe.test(inner)));
    if (!mayMatch) return;

    let { sentence, matches, coCited } = render(inner);
    const notes = [];
    let how = null;
    if (matches.includes("linked")) how = "linked";
    else if (matches.includes("marker")) how = "marker";
    else if (authorYear && authorYear.test(sentence)) {
      how = "marker"; // bare-text marker GROBID did not tag as a reference at all
      sentence = sentence.replace(authorYear, (m) => `${OPEN}${m}${CLOSE}`);
    } else if (nameRe && ((nameRe.lastIndex = 0), nameRe.test(sentence))) {
      how = "name";
      sentence = sentence.replace(nameRe, (m) => `${OPEN}${m}${CLOSE}`);
    }
    if (!how) return;

    if (how === "marker" && !numericStyle && bib.ambiguous) notes.push("author-year marker is shared by another reference");
    if (how === "marker") notes.push("matched by marker text; GROBID did not link this citation");
    if (sentence.length > 600) notes.push("sentence trimmed around the target; probably a flattened table or list");

    let before = "";
    let after = "";
    if (block.tag === "s") {
      const sibs = sentenceSiblings.get(block.parentId) || [];
      const i = sibs.indexOf(index);
      if (i > 0) before = text(blocks[sibs[i - 1]].inner);
      if (i >= 0 && i < sibs.length - 1) after = text(blocks[sibs[i + 1]].inner);
    }
    contexts.push({
      match: how,
      section: block.section,
      sentence: windowAround(sentence),
      before: clip(before, 400, "end"),
      after: clip(after, 400, "start"),
      co_cited: coCited,
      in_float: block.inFloat,
      notes,
    });
  });
  return { bib, contexts };
}
