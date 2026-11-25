// Offline tests for the Worker's context extractor. Run: npm test
// These mirror tests/test_arxiv_html.py so the two implementations stay in step.

import assert from "node:assert/strict";
import { test } from "node:test";
import { extractContexts, shortName, splitSentences } from "../src/arxiv.js";

const TARGET = { title: "Widget-X2: A Faster Way to Frobnicate", arxivId: "2501.00001" };
const page = (body, refs) =>
  `<html><body><article class="ltx_document">${body}<section id="bib" class="ltx_bibliography"><h2 class="ltx_title ltx_title_bibliography">References</h2><ul class="ltx_biblist">${refs}</ul></section></article></body></html>`;
const bib = (id, text) => `<li id="${id}" class="ltx_bibitem ltx_bib_article"><span class="ltx_tag ltx_tag_bibitem">[x]</span><span class="ltx_bibblock">${text}</span></li>`;
const REFS = bib("bib.bib1", "A. Smith. Something unrelated. 2020.") + bib("bib.bib2", "B. Lee and C. Kim. Widget-x2: A faster way to frobnicate. In ICML, 2025.");
const section = (title, inner) => `<section class="ltx_section"><h2 class="ltx_title ltx_title_section"><span class="ltx_tag">2 </span>${title}</h2>${inner}</section>`;

test("splitSentences keeps abbreviations and initials together", () => {
  assert.deepEqual(splitSentences("We follow Lee et al. (2025) closely. It works, e.g. on text. See Fig. 3 for more."), [
    "We follow Lee et al. (2025) closely.",
    "It works, e.g. on text.",
    "See Fig. 3 for more.",
  ]);
  assert.deepEqual(splitSentences("Proposed by J. Doe in 2020. Others followed."), ["Proposed by J. Doe in 2020.", "Others followed."]);
});

test("shortName only returns coined names", () => {
  assert.equal(shortName("Widget-X2: A Faster Way to Frobnicate"), "Widget-X2");
  assert.equal(shortName("Attention Is All You Need"), null);
  assert.equal(shortName("$τ$-bench: A Benchmark"), null);
});

test("author-year citation where only the year is a link", () => {
  const body = section(
    "Related Work",
    `<div class="ltx_para"><p class="ltx_p">First sentence. Prior work is fast <cite class="ltx_cite ltx_citemacro_citep">(Smith, <a href="#bib.bib1" title="" class="ltx_ref">2020</a>; Lee and Kim, <a href="#bib.bib2" title="" class="ltx_ref">2025</a>)</cite>. Last sentence.</p></div>`,
  );
  const { bib: entry, contexts } = extractContexts(page(body, REFS), TARGET);
  assert.deepEqual(entry.ids, ["bib.bib2"]);
  assert.equal(contexts.length, 1);
  const c = contexts[0];
  assert.deepEqual([c.match, c.section, c.co_cited, c.in_float], ["linked", "2 Related Work", 1, false]);
  assert.equal(c.sentence, "Prior work is fast (Smith, 2020; <TARGET>Lee and Kim, 2025</TARGET>).");
  assert.deepEqual([c.before, c.after], ["First sentence.", "Last sentence."]);
});

test("numbered citation in a group", () => {
  const body = section("Intro", `<p class="ltx_p">Reasoning models <cite class="ltx_cite">[<a href="#bib.bib2" class="ltx_ref">2</a>, <a href="#bib.bib1" class="ltx_ref">1</a>]</cite> are popular.</p>`);
  const { contexts } = extractContexts(page(body, REFS), TARGET);
  assert.equal(contexts.length, 1);
  assert.equal(contexts[0].sentence, "Reasoning models [<TARGET>2</TARGET>, 1] are popular.");
  assert.equal(contexts[0].co_cited, 1);
});

test("table row is kept whole, with maths as LaTeX", () => {
  const body = section(
    "Results",
    `<table class="ltx_tabular"><tr class="ltx_tr"><td class="ltx_td">Widget-X2 <cite class="ltx_cite">(Lee and Kim, <a href="#bib.bib2" class="ltx_ref">2025</a>)</cite></td><td class="ltx_td">62.1<math alttext="\\pm" display="inline"><semantics><mo>±</mo><annotation encoding="application/x-tex">\\pm</annotation></semantics></math>0.6</td></tr></table>`,
  );
  const { contexts } = extractContexts(page(body, REFS), TARGET);
  assert.equal(contexts.length, 1);
  assert.equal(contexts[0].sentence, "Widget-X2 (<TARGET>Lee and Kim, 2025</TARGET>) 62.1\\pm0.6");
  assert.equal(contexts[0].in_float, true);
});

test("name mention without a citation", () => {
  const body = section("Results", `<p class="ltx_p">Our model beats Widget-X2 by two points. Nothing here.</p>`);
  const { contexts } = extractContexts(page(body, REFS), TARGET);
  assert.deepEqual(contexts.map((c) => c.match), ["name"]);
  assert.equal(contexts[0].sentence, "Our model beats <TARGET>Widget-X2</TARGET> by two points.");
});

test("preprint and published version listed as two references", () => {
  const refs = REFS + bib("bib.bib3", "B. Lee and C. Kim. Widget-X2: a faster way to frobnicate. arXiv preprint arXiv:2501.00001, 2025.");
  const body = section("Intro", `<p class="ltx_p">One <cite class="ltx_cite">[<a href="#bib.bib2" class="ltx_ref">2</a>]</cite>. Two <cite class="ltx_cite">[<a href="#bib.bib3" class="ltx_ref">3</a>]</cite>.</p>`);
  const { bib: entry, contexts } = extractContexts(page(body, refs), TARGET);
  assert.deepEqual(entry.ids, ["bib.bib2", "bib.bib3"]);
  assert.equal(contexts.length, 2);
});

test("target missing from the reference list", () => {
  const { bib: entry, contexts } = extractContexts(page(section("Intro", `<p class="ltx_p">Nothing.</p>`), bib("bib.bib1", "A. Smith. Other. 2020.")), TARGET);
  assert.equal(entry, null);
  assert.deepEqual(contexts, []);
});
