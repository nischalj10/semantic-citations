// semantic-citations web app.
//
//   GET /                              the page
//   GET /api/paper?id=<arxiv link>     the paper and the works that cite it
//   GET /api/citations?target=W1&work=W2
//                                      every citation of W1 inside W2, labelled
//
// The browser asks for the paper first, then for each citing work in turn, so
// one request never needs more than a few dozen outbound calls and the page can
// show progress. Everything is cached in KV: a paper is only ever paid for once.
//
// The citations endpoint takes IDs, never text. It only reads works that
// OpenAlex says cite the target, so it cannot be used as a general-purpose
// proxy to the OpenAI key.

import page from "./page.html";
import { MODEL, UserError, decide, fetchFulltext, lookupPaper, renderInput, toLookupKey } from "./pipeline.js";
import { extractContexts } from "./tei.js";

const VERSION = "v1"; // bump to invalidate cached results after a prompt change
const PAPER_TTL = 60 * 60 * 6; // citing lists grow, so recheck every six hours
const TARGET_TTL = 60 * 60 * 24 * 7;

const limit = (env, name, fallback) => Number(env[name] ?? fallback);

const json = (body, status = 200, cache = "no-store") =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": cache } });

/** What the browser gets: the stored record without the abstract. */
const publicPaper = ({ abstract, ...paper }, maxCiting) => ({ ...paper, shown: paper.citing.length, max_citing: maxCiting });

async function handlePaper(url, env, ctx) {
  const key = toLookupKey(url.searchParams.get("id"));
  const maxCiting = limit(env, "MAX_CITING", 30);
  const lookupKey = `${VERSION}:lookup:${key.toLowerCase()}`;
  const cached = await env.CACHE.get(lookupKey, "json");
  if (cached) return json(publicPaper(cached, maxCiting));

  const paper = await lookupPaper(env, key, maxCiting);
  // The browser asks for citations as soon as this returns, so the record must be stored first.
  await env.CACHE.put(`${VERSION}:paper:${paper.id}`, JSON.stringify(paper), { expirationTtl: TARGET_TTL });
  ctx.waitUntil(env.CACHE.put(lookupKey, JSON.stringify(paper), { expirationTtl: PAPER_TTL }));
  console.log(JSON.stringify({ event: "paper_lookup", paper: paper.id, citing: paper.total_citing }));
  return json(publicPaper(paper, maxCiting));
}

async function handleCitations(url, env, ctx) {
  const target = url.searchParams.get("target") || "";
  const work = url.searchParams.get("work") || "";
  if (!/^W\d{5,}$/.test(target) || !/^W\d{5,}$/.test(work)) throw new UserError(400, "Missing or malformed paper IDs.");

  const resultKey = `${VERSION}:cite:${target}:${work}`;
  const cached = await env.CACHE.get(resultKey, "json");
  if (cached) return json(cached);

  const paper = await env.CACHE.get(`${VERSION}:paper:${target}`, "json");
  if (!paper) throw new UserError(409, "Look the paper up again first; its details have expired.");
  const citing = paper.citing.find((w) => w.id === work);
  if (!citing) throw new UserError(400, "That work is not in this paper's list of citing works.");

  const finish = (result) => {
    ctx.waitUntil(env.CACHE.put(resultKey, JSON.stringify(result)));
    return json(result);
  };
  if (!citing.has_fulltext) return finish({ status: "no_fulltext", contexts: [] });

  // Spend cap: each uncached full text costs $0.01 of the OpenAlex allowance.
  const dayKey = `budget:${new Date().toISOString().slice(0, 10)}`;
  const used = Number((await env.CACHE.get(dayKey)) || 0);
  if (used >= limit(env, "DAILY_FULLTEXT_CAP", 80)) {
    throw new UserError(429, "This site has read as many new papers as it can afford today. Papers that were already read still load.");
  }
  const xml = await fetchFulltext(env, work);
  if (!xml) return finish({ status: "no_fulltext", contexts: [] });
  ctx.waitUntil(env.CACHE.put(dayKey, String(used + 1), { expirationTtl: 60 * 60 * 48 }));

  const { bib, contexts } = extractContexts(xml, { title: paper.title, arxivId: paper.arxiv_id, doi: paper.doi ? paper.doi.split("doi.org/").pop() : null });
  if (!bib) return finish({ status: "not_in_references", contexts: [] });
  if (!contexts.length) return finish({ status: "no_intext_citation", contexts: [] });

  const maxContexts = limit(env, "MAX_CONTEXTS_PER_WORK", 8);
  const kept = contexts.slice(0, maxContexts);
  const labelled = await Promise.all(
    kept.map(async (context) => ({ ...context, ...(await decide(env, renderInput(paper, citing.title, context))) })),
  );
  console.log(JSON.stringify({ event: "work_read", target, work, contexts: labelled.length, model: MODEL }));
  return finish({ status: "ok", contexts: labelled, not_shown: contexts.length - kept.length });
}

export default {
  async fetch(request, env, ctx) {
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
      if (url.pathname === "/api/paper") return await handlePaper(url, env, ctx);
      if (url.pathname === "/api/citations") return await handleCitations(url, env, ctx);
      return json({ error: "Not found." }, 404);
    } catch (err) {
      if (err instanceof UserError) return json({ error: err.message, ...err.extra }, err.status);
      console.log(JSON.stringify({ event: "unhandled_error", path: url.pathname, message: String(err && err.message), stack: String(err && err.stack).slice(0, 600) }));
      return json({ error: "Something went wrong on our side. Try again in a minute." }, 500);
    }
  },
};
