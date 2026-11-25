// Offline tests for the Worker's context extractor. Run: npm test
// These mirror tests/test_tei.py so the two implementations stay in step.

import assert from "node:assert/strict";
import { test } from "node:test";
import { expandNumbers, extractContexts, shortName, wrap } from "../src/tei.js";

const TARGET = { title: "Widget-X2: A Faster Way to Frobnicate", arxivId: "2501.00001" };
const tei = (body, refs) =>
  `<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc/></teiHeader><text><body>${body}</body><back><div type="references"><listBibl>${refs}</listBibl></div></back></text></TEI>`;
const bib = (id, title, surname, year) =>
  `<biblStruct xml:id="${id}"><analytic><title level="a">${title}</title><author><persName><forename>A</forename><surname>${surname}</surname></persName></author></analytic><monogr><imprint><date when="${year}"/></imprint></monogr></biblStruct>`;
const REFS = bib("b0", "Something Unrelated", "Smith", "2020") + bib("b1", "Widget-x2: A faster way to frobnicate", "Lee", "2025");

test("expandNumbers", () => {
  assert.deepEqual(expandNumbers("13;14;15"), [13, 14, 15]);
  assert.deepEqual(expandNumbers("[10-12, 20]"), [10, 11, 12, 20]);
  assert.deepEqual(expandNumbers("Lee et al., 2025"), []);
});

test("wrap keeps punctuation outside the tags", () => {
  assert.equal(wrap("(Lee et al., 2025;"), "(<TARGET>Lee et al., 2025</TARGET>;");
  assert.equal(wrap(", Lee et al., 2025"), ", <TARGET>Lee et al., 2025</TARGET>");
  assert.equal(wrap("[2]"), "[<TARGET>2</TARGET>]");
});

test("shortName only returns coined names", () => {
  assert.equal(shortName("Widget-X2: A Faster Way to Frobnicate"), "Widget-X2");
  assert.equal(shortName("Attention Is All You Need"), null);
  assert.equal(shortName("Reasoning: A Survey"), null);
});

test("linked citation with neighbours and co-citation count", () => {
  const body = `<div><head n="2">Related Work</head><p><s>First sentence.</s>
    <s>Prior work is fast <ref type="bibr" target="#b0">(Smith, 2020;</ref> <ref type="bibr" target="#b1">Lee et al., 2025)</ref>.</s>
    <s>Last sentence.</s></p></div>`;
  const { bib: entry, contexts } = extractContexts(tei(body, REFS), TARGET);
  assert.equal(entry.number, 2);
  assert.equal(contexts.length, 1);
  const c = contexts[0];
  assert.deepEqual([c.match, c.section, c.co_cited], ["linked", "2 Related Work", 1]);
  assert.ok(c.sentence.includes("<TARGET>Lee et al., 2025</TARGET>)"));
  assert.deepEqual([c.before, c.after], ["First sentence.", "Last sentence."]);
});

test("unlinked numeric marker", () => {
  const body = `<div><head>Intro</head><p><s>See <ref type="bibr" target="#b0">1</ref> for details.</s>
    <s>Reasoning models <ref type="bibr">2;3;4</ref> are popular.</s></p></div>`;
  const refs = REFS + bib("b2", "Third", "Kim", "2021") + bib("b3", "Fourth", "Park", "2022");
  const { contexts } = extractContexts(tei(body, refs), TARGET);
  assert.equal(contexts.length, 1);
  assert.deepEqual([contexts[0].match, contexts[0].co_cited], ["marker", 2]);
  assert.ok(contexts[0].sentence.includes("<TARGET>2</TARGET>;3;4"));
});

test("unlinked author-year marker", () => {
  const body = `<div><head>Intro</head><p><s>Rewards are static <ref type="bibr">[Lee et al., 2025</ref><ref type="bibr">, Kim, 2021]</ref>.</s></p></div>`;
  const { contexts } = extractContexts(tei(body, REFS), TARGET);
  assert.equal(contexts[0].match, "marker");
  assert.ok(contexts[0].sentence.includes("[<TARGET>Lee et al., 2025</TARGET>"));
});

test("name mention without a citation", () => {
  const body = `<div><head>Results</head><p><s>Our model beats Widget-X2 by two points.</s><s>Nothing here.</s></p></div>`;
  const { contexts } = extractContexts(tei(body, REFS), TARGET);
  assert.deepEqual(contexts.map((c) => c.match), ["name"]);
  assert.ok(contexts[0].sentence.includes("<TARGET>Widget-X2</TARGET>"));
});

test("target missing from the reference list", () => {
  const { bib: entry, contexts } = extractContexts(tei("<div><p><s>Nothing.</s></p></div>", bib("b0", "Other", "Smith", "2020")), TARGET);
  assert.equal(entry, null);
  assert.deepEqual(contexts, []);
});
