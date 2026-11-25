// Check that the Worker's context extractor matches the Python one.
//
//   node worker/test/parity.mjs
//
// Compares against data/<slug>/contexts.jsonl using the full texts in cache/tei/
// (downloaded by `python -m semantic_citations run`). Skips papers that are not cached.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { extractContexts } from "../src/tei.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const fields = ["match", "section", "sentence", "before", "after", "co_cited", "in_float", "notes"];
let compared = 0;
let failures = 0;
let slowest = 0;

for (const slug of readdirSync(join(root, "data"))) {
  const dir = join(root, "data", slug);
  if (!existsSync(join(dir, "contexts.jsonl"))) continue;
  const cited = JSON.parse(readFileSync(join(dir, "cited.json"), "utf8"));
  const arxiv = /(\d{4}\.\d{4,5})/.exec(cited.doi || "");
  const target = { title: cited.title, arxivId: arxiv ? arxiv[1] : null, doi: (cited.doi || "").split("doi.org/").pop() || null };
  const expected = new Map();
  for (const line of readFileSync(join(dir, "contexts.jsonl"), "utf8").split("\n").filter(Boolean)) {
    const row = JSON.parse(line);
    if (!expected.has(row.citing_work)) expected.set(row.citing_work, []);
    expected.get(row.citing_work).push(row);
  }
  for (const work of JSON.parse(readFileSync(join(dir, "citing_works.json"), "utf8"))) {
    const path = join(root, "cache", "tei", `${work.openalex_id}.xml`);
    if (!existsSync(path)) continue;
    const xml = readFileSync(path, "utf8");
    const t0 = performance.now();
    const { contexts } = extractContexts(xml, target);
    const ms = performance.now() - t0;
    slowest = Math.max(slowest, ms);
    const want = expected.get(work.openalex_id) || [];
    compared++;
    let ok = contexts.length === want.length;
    for (let i = 0; ok && i < want.length; i++) {
      for (const f of fields) {
        if (JSON.stringify(contexts[i][f]) !== JSON.stringify(want[i][f])) {
          ok = false;
          console.log(`  ${work.openalex_id}#${i + 1} differs in ${f}\n    python: ${JSON.stringify(want[i][f])}\n    worker: ${JSON.stringify(contexts[i][f])}`);
        }
      }
    }
    if (!ok) failures++;
    console.log(`${ok ? "ok  " : "FAIL"} ${work.openalex_id}  ${contexts.length}/${want.length} contexts  ${(xml.length / 1024).toFixed(0)} KB  ${ms.toFixed(1)} ms`);
  }
}

console.log(`\n${compared} papers compared, ${failures} differ, slowest extraction ${slowest.toFixed(1)} ms`);
if (compared === 0) console.log("Nothing cached to compare. Run the Python pipeline first.");
process.exit(failures ? 1 : 0);
