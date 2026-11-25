// semantic-citations web app.
//
//   GET /                                    the page
//   GET /api/paper?id=<arxiv link>           the paper and the first page of works citing it
//   GET /api/citing?target=W1&page=2         further pages of citing works
//   GET /api/results?target=W1&offset=0      every citing work already read, in bulk
//   GET /api/citations?target=W1&work=W2&page=1
//                                            read one citing work and label each citation in it
//
// The list of citing works comes from OpenAlex (a fraction of a cent per paper).
// Their text comes from arXiv's HTML, which is free. The browser asks for one
// citing work at a time, so a request never needs more than a few dozen outbound
// calls and the page can show progress. Everything is stored in D1, so a citing
// paper is fetched and labelled once, for every visitor.
//
// The citations endpoint takes IDs, never text. It only reads works that
// OpenAlex says cite the target, so it cannot be used as a general-purpose
// proxy to the OpenAI key.

import page from "./page.html";
import { extractContexts } from "./arxiv.js";
import { MODEL, PAGE_SIZE, SOURCES, UserError, decide, fetchPaperHtml, listCiting, lookupPaper, renderInput, toLookupKey } from "./pipeline.js";

const VERSION = "v2"; // bump to discard stored results after a prompt or extractor change
const PAPER_TTL_MS = 6 * 60 * 60 * 1000; // citing lists grow, so recheck every six hours
const MAX_WAIT_MS = 20000; // longest a request will sleep for its turn at arXiv
const RESULTS_PAGE = 500;

const limit = (env, name, fallback) => Number(env[name] ?? fallback);
const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
const raw = (text) => new Response(text, { headers: JSON_HEADERS });
const isWorkId = (s) => /^W\d{5,}$/.test(s || "");

const fresh = (row) => (row && row.expires > Date.now() ? JSON.parse(row.json) : null);
const putPaper = (env, key, value) =>
  env.DB.prepare("INSERT OR REPLACE INTO papers (key, json, expires) VALUES (?1, ?2, ?3)").bind(key, JSON.stringify(value), Date.now() + PAPER_TTL_MS);
const putPage = (env, target, n, works) =>
  env.DB.prepare("INSERT OR REPLACE INTO pages (target, page, json, expires) VALUES (?1, ?2, ?3, ?4)").bind(target, n, JSON.stringify(works), Date.now() + PAPER_TTL_MS);

/** What the browser gets: the stored record without the abstract. */
function publicPaper({ abstract, ...paper }, env) {
  const listed = Math.min(paper.total_citing, limit(env, "MAX_CITING", 2000));
  return { ...paper, listed, pages: Math.ceil(listed / PAGE_SIZE), page_size: PAGE_SIZE };
}

async function handlePaper(url, env) {
  const key = toLookupKey(url.searchParams.get("id"));
  const lookupKey = `lookup:${key.toLowerCase()}`;
  const known = fresh(await env.DB.prepare("SELECT json, expires FROM papers WHERE key = ?1").bind(lookupKey).first());
  if (known) {
    const first = fresh(await env.DB.prepare("SELECT json, expires FROM pages WHERE target = ?1 AND page = 1").bind(known.id).first());
    if (first) return json({ ...publicPaper(known, env), citing: first });
  }

  const paper = known || (await lookupPaper(env, key));
  const { total, works } = await listCiting(env, paper.id, 1);
  paper.total_citing = total;
  // The browser asks for citations as soon as this returns, so store everything first.
  await env.DB.batch([putPaper(env, lookupKey, paper), putPaper(env, `paper:${paper.id}`, paper), putPage(env, paper.id, 1, works)]);
  console.log(JSON.stringify({ event: "paper_lookup", paper: paper.id, citing: total }));
  return json({ ...publicPaper(paper, env), citing: works });
}

async function handleCiting(url, env) {
  const target = url.searchParams.get("target");
  const n = Number(url.searchParams.get("page"));
  if (!isWorkId(target) || !Number.isInteger(n) || n < 1) throw new UserError(400, "Missing or malformed paper ID or page.");
  const [pageRow, paperRow] = await env.DB.batch([
    env.DB.prepare("SELECT json, expires FROM pages WHERE target = ?1 AND page = ?2").bind(target, n),
    env.DB.prepare("SELECT json, expires FROM papers WHERE key = ?1").bind(`paper:${target}`),
  ]);
  const stored = fresh(pageRow.results[0]);
  if (stored) return json({ citing: stored });
  const paper = paperRow.results[0] ? JSON.parse(paperRow.results[0].json) : null;
  if (!paper) throw new UserError(409, "Look the paper up again first; its details have expired.");
  if (n > publicPaper(paper, env).pages) return json({ citing: [] });
  const { works } = await listCiting(env, target, n);
  await putPage(env, target, n, works).run();
  return json({ citing: works });
}

/** Every stored result for a paper, a page at a time, without re-parsing the stored JSON. */
async function handleResults(url, env) {
  const target = url.searchParams.get("target");
  const offset = Number(url.searchParams.get("offset") || 0);
  if (!isWorkId(target) || !Number.isInteger(offset) || offset < 0) throw new UserError(400, "Missing or malformed paper ID.");
  const { results } = await env.DB.prepare("SELECT work, json FROM results WHERE version = ?1 AND target = ?2 ORDER BY work LIMIT ?3 OFFSET ?4")
    .bind(VERSION, target, RESULTS_PAGE, offset)
    .all();
  const body = results.map((r) => `${JSON.stringify(r.work)}:${r.json}`).join(",");
  return raw(`{"results":{${body}},"next":${results.length === RESULTS_PAGE ? offset + RESULTS_PAGE : "null"}}`);
}

/**
 * Fetch a paper's HTML, taking turns: one request per host every `gapMs`,
 * across all visitors. The next free slot lives in D1. A short wait is slept
 * through; a long one is handed back to the browser to retry.
 */
async function getHtml(env, source, arxivId, hint) {
  const { gapMs } = SOURCES[source];
  const now = Date.now();
  const row = await env.DB.prepare("SELECT next_at FROM pace WHERE host = ?1").bind(source).first();
  const backlog = row ? row.next_at - now : 0;
  if (backlog > MAX_WAIT_MS) {
    throw new UserError(429, "Waiting for a turn to fetch from arXiv.", { retry_after: Math.ceil((backlog - MAX_WAIT_MS) / 1000) + 1, source, ...hint });
  }
  const slot = await env.DB.prepare("INSERT INTO pace (host, next_at) VALUES (?1, ?2) ON CONFLICT(host) DO UPDATE SET next_at = MAX(next_at, ?3) + ?4 RETURNING next_at")
    .bind(source, now + gapMs, now, gapMs)
    .first();
  const wait = slot.next_at - gapMs - Date.now();
  if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
  return fetchPaperHtml(source, arxivId);
}

async function handleCitations(url, env) {
  const target = url.searchParams.get("target");
  const work = url.searchParams.get("work");
  const n = Number(url.searchParams.get("page") || 1);
  if (!isWorkId(target) || !isWorkId(work) || !Number.isInteger(n) || n < 1) throw new UserError(400, "Missing or malformed paper IDs.");

  const day = new Date().toISOString().slice(0, 10);
  const [storedRow, pageRow, paperRow, countRow] = await env.DB.batch([
    env.DB.prepare("SELECT json FROM results WHERE version = ?1 AND target = ?2 AND work = ?3").bind(VERSION, target, work),
    env.DB.prepare("SELECT json FROM pages WHERE target = ?1 AND page = ?2").bind(target, n),
    env.DB.prepare("SELECT json FROM papers WHERE key = ?1").bind(`paper:${target}`),
    env.DB.prepare("SELECT n FROM counters WHERE day = ?1").bind(day),
  ]);
  if (storedRow.results[0]) return raw(storedRow.results[0].json);
  if (!pageRow.results[0] || !paperRow.results[0]) throw new UserError(409, "Look the paper up again first; its details have expired.");
  const paper = JSON.parse(paperRow.results[0].json);
  const citing = JSON.parse(pageRow.results[0].json).find((w) => w.id === work);
  if (!citing) throw new UserError(400, "That work is not in this paper's list of citing works.");

  const finish = async (result) => {
    const text = JSON.stringify(result);
    await env.DB.prepare("INSERT OR REPLACE INTO results (version, target, work, json, created) VALUES (?1, ?2, ?3, ?4, ?5)").bind(VERSION, target, work, text, Date.now()).run();
    return raw(text);
  };
  if (!citing.arxiv_id) return finish({ status: "not_on_arxiv", contexts: [] });
  if ((countRow.results[0]?.n ?? 0) >= limit(env, "DAILY_NEW_PAPERS_CAP", 1500)) {
    throw new UserError(429, "This site has read as many new papers as it is set to label in a day. Papers that were already read still load.");
  }

  // ar5iv first, then arXiv's latest version if ar5iv has no copy or its copy does not cite the target.
  const lookFor = { title: paper.title, arxivId: paper.arxiv_id, doi: paper.doi ? paper.doi.split("doi.org/").pop() : null };
  const startAtArxiv = url.searchParams.get("source") === "arxiv";
  let sawHtml = url.searchParams.get("saw") === "1";
  let contexts = null;
  for (const source of startAtArxiv ? ["arxiv"] : ["ar5iv", "arxiv"]) {
    const html = await getHtml(env, source, citing.arxiv_id, { saw_html: sawHtml });
    if (!html) continue;
    sawHtml = true;
    const found = extractContexts(html, lookFor);
    if (found.bib) {
      contexts = found.contexts;
      break;
    }
  }
  if (contexts === null) return finish({ status: sawHtml ? "not_in_references" : "no_html", contexts: [] });
  if (!contexts.length) return finish({ status: "no_intext_citation", contexts: [] });

  const kept = contexts.slice(0, limit(env, "MAX_CONTEXTS_PER_WORK", 8));
  const labelled = await Promise.all(kept.map(async (context) => ({ ...context, ...(await decide(env, renderInput(paper, citing.title, context))) })));
  await env.DB.prepare("INSERT INTO counters (day, n) VALUES (?1, 1) ON CONFLICT(day) DO UPDATE SET n = n + 1").bind(day).run();
  console.log(JSON.stringify({ event: "work_read", target, work, contexts: labelled.length, model: MODEL }));
  return finish({ status: "ok", contexts: labelled, not_shown: contexts.length - kept.length });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method !== "GET" && request.method !== "HEAD") return json({ error: "Method not allowed." }, 405);
      if (url.pathname === "/") {
        return new Response(page, {
          headers: {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy":
              "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; " +
              "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
          },
        });
      }
      if (url.pathname === "/api/paper") return await handlePaper(url, env);
      if (url.pathname === "/api/citing") return await handleCiting(url, env);
      if (url.pathname === "/api/results") return await handleResults(url, env);
      if (url.pathname === "/api/citations") return await handleCitations(url, env);
      return json({ error: "Not found." }, 404);
    } catch (err) {
      if (err instanceof UserError) return json({ error: err.message, ...err.extra }, err.status);
      console.log(JSON.stringify({ event: "unhandled_error", path: url.pathname, message: String(err && err.message), stack: String(err && err.stack).slice(0, 600) }));
      return json({ error: "Something went wrong on our side. Try again in a minute." }, 500);
    }
  },
};
