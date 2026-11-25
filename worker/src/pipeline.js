// OpenAlex lookups, arXiv HTML fetches and OpenAI Decisions API calls.
// Mirrors semantic_citations/openalex.py, arxiv.py, decisions.py and taxonomy.py.

import PROMPT from "./prompt.json";

const OPENALEX = "https://api.openalex.org";
export const PAGE_SIZE = 100; // citing works per OpenAlex request

// Two hosts serve the same LaTeXML HTML. ar5iv (arXiv Labs) sets no crawl delay;
// arxiv.org's robots.txt asks for 15 seconds between requests. ar5iv goes first
// and arxiv.org is the fallback, because ar5iv keeps the version it converted
// and that can predate the citation we are looking for.
export const SOURCES = {
  ar5iv: { url: "https://ar5iv.labs.arxiv.org/html/", gapMs: 3000 },
  arxiv: { url: "https://arxiv.org/html/", gapMs: 15000 },
};
const USER_AGENT = "semantic-citations (+https://github.com/nischalj10/semantic-citations)";
const DECISIONS_URL = "https://api.openai.com/v1/decisions";
export const MODEL = "gpt-6-luna";
export const ROTATIONS = 4;
export const REVIEW_BELOW = 0.9;

/** An error whose message is safe to show to the visitor. */
export class UserError extends Error {
  /** @param extra fields added to the JSON error body, e.g. { retry_after: 15 } */
  constructor(status, message, extra = {}) {
    super(message);
    this.status = status;
    this.extra = extra;
  }
}

/** Accept an arXiv URL or ID, a DOI or DOI URL, or an OpenAlex work ID. */
export function toLookupKey(identifier) {
  const s = String(identifier || "").trim();
  if (s.length > 300) throw new UserError(400, "That link is too long to be a paper.");
  let m = /arxiv\.org\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5})/i.exec(s) || /^(?:arxiv:)?(\d{4}\.\d{4,5})(?:v\d+)?$/i.exec(s);
  if (m) return `doi:10.48550/arXiv.${m[1]}`;
  m = /(10\.\d{4,9}\/[^\s?#]+)/.exec(s);
  if (m) return `doi:${m[1]}`;
  m = /(W\d{5,})$/.exec(s);
  if (m) return m[1];
  throw new UserError(400, "That doesn't look like an arXiv link. Paste something like https://arxiv.org/abs/2512.00601.");
}

const shortId = (work) => work.id.split("/").pop();
const plain = (s) => String(s || "").replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();

function abstractOf(work) {
  const words = [];
  for (const [word, positions] of Object.entries(work.abstract_inverted_index || {})) for (const p of positions) words.push([p, word]);
  return words.sort((a, b) => a[0] - b[0]).map((w) => w[1]).join(" ");
}

async function openalex(env, url) {
  const res = await fetch(`${url}${url.includes("?") ? "&" : "?"}api_key=${env.OPENALEX_API_KEY}`);
  if (res.status === 404) return null;
  if (res.status === 429) {
    // Two different limits answer 429: the daily allowance (come back tomorrow) and
    // short-term throttles such as the one on new API keys (come back in seconds).
    const remaining = Number(res.headers.get("x-ratelimit-remaining-usd"));
    const needed = Number(res.headers.get("x-ratelimit-cost-required-usd") || 0);
    if (Number.isFinite(remaining) && remaining < needed) {
      throw new UserError(503, "OpenAlex's daily allowance for this site is used up. Papers that were already read still load.");
    }
    const wait = Math.min(Math.max(Number(res.headers.get("retry-after")) || 15, 5), 120);
    throw new UserError(429, "OpenAlex is limiting how fast this site can read new papers.", { retry_after: wait });
  }
  if (!res.ok) throw new UserError(502, `OpenAlex returned an error (${res.status}). Try again in a minute.`);
  return res;
}

/** The arXiv ID of an OpenAlex work, from its DOI or any of its locations. */
function arxivIdOf(work) {
  const places = [work.doi || ""];
  for (const loc of work.locations || []) places.push(loc.landing_page_url || "", loc.pdf_url || "");
  for (const place of places) {
    const m = /arxiv\.org\/(?:abs|pdf|html)\/(\d{4}\.\d{4,5})/i.exec(place) || /10\.48550\/arxiv\.(\d{4}\.\d{4,5})/i.exec(place);
    if (m) return m[1];
  }
  return null;
}

/** One page of the works citing `targetId`, most-cited first. Costs $0.0001. */
export async function listCiting(env, targetId, page) {
  const res = await openalex(
    env,
    `${OPENALEX}/works?filter=cites:${targetId}&per_page=${PAGE_SIZE}&page=${page}&sort=cited_by_count:desc` +
      "&select=id,doi,title,publication_date,cited_by_count,locations",
  );
  const body = await res.json();
  return {
    total: body.meta.count,
    works: body.results.map((w) => ({
      id: shortId(w),
      title: plain(w.title) || "Untitled work",
      doi: w.doi || null,
      published: w.publication_date || null,
      venue: (w.locations || []).map((l) => l.source && l.source.display_name).find(Boolean) || null,
      cited_by_count: w.cited_by_count || 0,
      arxiv_id: arxivIdOf(w),
    })),
  };
}

/** Resolve a paper. Free. */
export async function lookupPaper(env, key) {
  const res = await openalex(env, `${OPENALEX}/works/${key}?select=id,doi,title,publication_year,cited_by_count,ids,abstract_inverted_index`);
  if (!res) throw new UserError(404, "OpenAlex has no record of that paper. Very recent preprints can take a few weeks to appear.");
  const work = await res.json();
  const arxiv = /(\d{4}\.\d{4,5})/.exec(JSON.stringify(work.ids || {}) + (work.doi || ""));
  return {
    id: shortId(work),
    title: plain(work.title),
    doi: work.doi || null,
    arxiv_id: arxiv ? arxiv[1] : null,
    year: work.publication_year || null,
    abstract: abstractOf(work),
  };
}

/**
 * A paper's HTML from one source, or null when that source has nothing usable:
 * a missing paper redirects (ar5iv) or 404s (arxiv.org), and a failed conversion
 * is a page with no reference list.
 */
export async function fetchPaperHtml(source, arxivId) {
  const res = await fetch(SOURCES[source].url + arxivId, { headers: { "User-Agent": USER_AGENT }, redirect: "manual" });
  if (res.status === 429 || res.status === 503) {
    const wait = Math.min(Math.max(Number(res.headers.get("retry-after")) || 30, 5), 120);
    throw new UserError(429, "arXiv asked this site to slow down.", { retry_after: wait, source });
  }
  if (res.status !== 200) return null;
  const html = await res.text();
  return html.includes("ltx_bibitem") ? html : null;
}

const rotate = (items, k) => items.slice(k % items.length).concat(items.slice(0, k % items.length));

function buildQuestions(rotation) {
  return [
    { type: "choice", ...PROMPT.function, choices: rotate(PROMPT.function.choices, rotation) },
    { type: "choice", ...PROMPT.stance, choices: rotate(PROMPT.stance.choices, rotation) },
    { type: "predicate", ...PROMPT.own_evidence },
  ];
}

export function renderInput(cited, citingTitle, context) {
  let abstract = (cited.abstract || "").trim();
  if (abstract.length > 1200) {
    const head = abstract.slice(0, 1200);
    abstract = head.slice(0, head.lastIndexOf(" ")) + " ...";
  }
  const lines = ["CITED PAPER", `Title: ${cited.title}`];
  if (abstract) lines.push(`Abstract: ${abstract}`);
  lines.push("", "CITING PAPER", `Title: ${citingTitle}`, `Section: ${context.section || "unknown"}`, "", "PASSAGE");
  if (context.before) lines.push(context.before);
  lines.push(`>>> ${context.sentence}`);
  if (context.after) lines.push(context.after);
  return lines.join("\n");
}

async function askOnce(env, input, rotation) {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(DECISIONS_URL, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model: MODEL, input, questions: buildQuestions(rotation) }),
    });
    if (res.ok) return res.json();
    if ((res.status === 429 || res.status >= 500) && attempt < 2) {
      await new Promise((r) => setTimeout(r, 500 * 2 ** attempt));
      continue;
    }
    console.log(JSON.stringify({ event: "decisions_error", status: res.status, body: (await res.text()).slice(0, 300) }));
    throw new UserError(502, "The decision model returned an error. Try again in a minute.");
  }
}

const round4 = (x) => Math.round(x * 1e4) / 1e4;

/** Classify one citation context: probabilities averaged over rotated option orders. */
export async function decide(env, input) {
  const responses = await Promise.all(Array.from({ length: ROTATIONS }, (_, k) => askOnce(env, input, k)));
  const sums = {};
  const tops = {};
  const predicates = {};
  for (const resp of responses) {
    for (const ans of resp.answers) {
      if (ans.type === "choice") {
        sums[ans.name] ??= {};
        for (const p of ans.probabilities) sums[ans.name][p.value] = (sums[ans.name][p.value] || 0) + p.probability;
        (tops[ans.name] ??= []).push(ans.choice);
      } else if (ans.type === "predicate") {
        predicates[ans.name] = (predicates[ans.name] || 0) + ans.probability;
      }
    }
  }
  const out = {};
  for (const [name, bySum] of Object.entries(sums)) {
    const n = tops[name].length;
    const probabilities = {};
    let label = null;
    for (const [value, total] of Object.entries(bySum)) {
      probabilities[value] = round4(total / n);
      if (label === null || probabilities[value] > probabilities[label]) label = value;
    }
    out[name] = { label, confidence: probabilities[label], probabilities, order_sensitive: new Set(tops[name]).size > 1 };
  }
  for (const [name, total] of Object.entries(predicates)) out[name] = { probability: round4(total / ROTATIONS) };
  if (!out.function || !out.stance || !out.own_evidence) throw new UserError(502, "The decision model declined to label this citation.");

  const evidence = out.own_evidence.probability >= 0.5;
  out.cito = out.stance.label !== "neutral" ? PROMPT.cito_stance[`${out.stance.label}|${evidence}`] : PROMPT.cito_function[out.function.label];
  out.needs_review = Math.min(out.function.confidence, out.stance.confidence) < REVIEW_BELOW;
  return out;
}
