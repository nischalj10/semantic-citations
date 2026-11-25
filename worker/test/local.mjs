// Run the Worker in plain Node with an in-memory cache, without a Cloudflare login.
//
//   npm run build && node test/local.mjs        then open http://localhost:8787
//
// Reads keys from ../.env. Full texts already in ../cache/tei/ are served from
// disk, so re-running a paper the Python pipeline has seen costs no OpenAlex budget.
// (Behind a proxy, start Node with NODE_USE_ENV_PROXY=1.)

import { existsSync, readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const env = { MAX_CITING: "30", MAX_CONTEXTS_PER_WORK: "8", DAILY_FULLTEXT_CAP: "80" };
for (const line of readFileSync(join(root, ".env"), "utf8").split("\n")) {
  const m = /^([A-Z_]+)=(.+)$/.exec(line.trim());
  if (m) env[m[1]] = m[2];
}

const store = new Map();
env.CACHE = {
  async get(key, type) {
    const v = store.get(key);
    return v === undefined ? null : type === "json" ? JSON.parse(v) : v;
  },
  async put(key, value) {
    store.set(key, value);
  },
};

const realFetch = globalThis.fetch;
export const calls = { openalex: 0, openai: 0, disk: 0 };
globalThis.fetch = async (input, init) => {
  const url = String(input instanceof Request ? input.url : input);
  const tei = /content\.openalex\.org\/works\/(W\d+)\.grobid-xml/.exec(url);
  if (tei && existsSync(join(root, "cache", "tei", `${tei[1]}.xml`))) {
    calls.disk++;
    return new Response(readFileSync(join(root, "cache", "tei", `${tei[1]}.xml`)));
  }
  if (url.includes("openalex.org")) calls.openalex++;
  if (url.includes("openai.com")) calls.openai++;
  return realFetch(input, init);
};

const { default: worker } = await import("../dist/worker.js");

export async function handle(path) {
  const pending = [];
  const res = await worker.fetch(new Request("http://localhost" + path), env, { waitUntil: (p) => pending.push(p) });
  await Promise.all(pending);
  return res;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 8787);
  createServer(async (req, res) => {
    const out = await handle(req.url);
    res.writeHead(out.status, Object.fromEntries(out.headers));
    res.end(Buffer.from(await out.arrayBuffer()));
  }).listen(port, () => console.log(`http://localhost:${port}`));
}
