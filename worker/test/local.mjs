// Run the Worker in plain Node with an in-memory database, without a Cloudflare login.
//
//   npm run build && node test/local.mjs        then open http://localhost:8787
//
// Reads keys from ../.env. arXiv pages already in ../cache/arxiv/ (downloaded by the
// Python pipeline) are served from disk. Behind a proxy, start Node with NODE_USE_ENV_PROXY=1.

import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const env = { MAX_CITING: "2000", MAX_CONTEXTS_PER_WORK: "8", DAILY_NEW_PAPERS_CAP: "1500" };
for (const line of readFileSync(join(root, ".env"), "utf8").split("\n")) {
  const m = /^([A-Z_]+)=(.+)$/.exec(line.trim());
  if (m) env[m[1]] = m[2];
}

// Enough of the D1 API for this Worker, on Node's built-in SQLite.
const db = new DatabaseSync(":memory:");
db.exec(readFileSync(join(here, "..", "schema.sql"), "utf8"));
const statement = (sql, args = []) => ({
  bind: (...values) => statement(sql, values),
  first: async () => db.prepare(sql).get(...args) ?? null,
  all: async () => ({ results: db.prepare(sql).all(...args) }),
  run: async () => ({ success: true, meta: db.prepare(sql).run(...args) }),
});
env.DB = { prepare: (sql) => statement(sql), batch: async (statements) => Promise.all(statements.map((s) => s.all())) };

const realFetch = globalThis.fetch;
export const calls = { openalex: 0, openai: 0, arxiv: 0, disk: 0 };
globalThis.fetch = async (input, init) => {
  const url = String(input instanceof Request ? input.url : input);
  const page = /(ar5iv\.labs\.arxiv\.org|arxiv\.org)\/html\/([0-9.]+)$/.exec(url);
  if (page) {
    const file = join(root, "cache", "arxiv", page[1].startsWith("ar5iv") ? "ar5iv" : "arxiv", `${page[2]}.html`);
    if (existsSync(file)) {
      calls.disk++;
      const html = readFileSync(file, "utf8");
      return html ? new Response(html) : new Response("", { status: 404 }); // an empty file records "no usable HTML"
    }
    calls.arxiv++;
  }
  if (url.includes("openalex.org")) calls.openalex++;
  if (url.includes("openai.com")) calls.openai++;
  return realFetch(input, init);
};

const { default: worker } = await import("../dist/worker.js");

export const handle = (path) => worker.fetch(new Request("http://localhost" + path), env);

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 8787);
  createServer(async (req, res) => {
    const out = await handle(req.url);
    res.writeHead(out.status, Object.fromEntries(out.headers));
    res.end(Buffer.from(await out.arrayBuffer()));
  }).listen(port, () => console.log(`http://localhost:${port}`));
}
