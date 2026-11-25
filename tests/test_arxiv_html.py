"""Offline tests for citation-context extraction from arXiv HTML. Run: python -m unittest
These mirror worker/test/arxiv.test.mjs so the two implementations stay in step."""

import unittest

from semantic_citations.arxiv_html import Target, extract_contexts, short_name, split_sentences
from semantic_citations.taxonomy import build_questions, cito_property

TARGET = Target(title="Widget-X2: A Faster Way to Frobnicate", arxiv_id="2501.00001")


def page(body: str, refs: str) -> str:
    return (
        f'<html><body><article class="ltx_document">{body}<section id="bib" class="ltx_bibliography">'
        f'<h2 class="ltx_title ltx_title_bibliography">References</h2><ul class="ltx_biblist">{refs}</ul></section></article></body></html>'
    )


def bib(ident: str, text: str) -> str:
    return f'<li id="{ident}" class="ltx_bibitem ltx_bib_article"><span class="ltx_tag ltx_tag_bibitem">[x]</span><span class="ltx_bibblock">{text}</span></li>'


def section(title: str, inner: str) -> str:
    return f'<section class="ltx_section"><h2 class="ltx_title ltx_title_section"><span class="ltx_tag">2 </span>{title}</h2>{inner}</section>'


REFS = bib("bib.bib1", "A. Smith. Something unrelated. 2020.") + bib("bib.bib2", "B. Lee and C. Kim. Widget-x2: A faster way to frobnicate. In ICML, 2025.")


class Helpers(unittest.TestCase):
    def test_split_sentences_keeps_abbreviations_and_initials_together(self):
        self.assertEqual(
            split_sentences("We follow Lee et al. (2025) closely. It works, e.g. on text. See Fig. 3 for more."),
            ["We follow Lee et al. (2025) closely.", "It works, e.g. on text.", "See Fig. 3 for more."],
        )
        self.assertEqual(split_sentences("Proposed by J. Doe in 2020. Others followed."), ["Proposed by J. Doe in 2020.", "Others followed."])

    def test_short_name_only_returns_coined_names(self):
        self.assertEqual(short_name("Widget-X2: A Faster Way to Frobnicate"), "Widget-X2")
        self.assertIsNone(short_name("Attention Is All You Need"))
        self.assertIsNone(short_name("$τ$-bench: A Benchmark"))

    def test_rotation_keeps_all_options(self):
        base = [c["value"] for c in build_questions(0)[0]["choices"]]
        rotated = [c["value"] for c in build_questions(1)[0]["choices"]]
        self.assertEqual(sorted(base), sorted(rotated))
        self.assertNotEqual(base, rotated)

    def test_cito_mapping(self):
        self.assertEqual(cito_property("compares", "neutral", True), "discusses")
        self.assertEqual(cito_property("background", "critiques", True), "disputes")
        self.assertEqual(cito_property("background", "supports", False), "agreesWith")


class Extraction(unittest.TestCase):
    def test_author_year_citation_where_only_the_year_is_a_link(self):
        body = section(
            "Related Work",
            '<div class="ltx_para"><p class="ltx_p">First sentence. Prior work is fast <cite class="ltx_cite ltx_citemacro_citep">(Smith, '
            '<a href="#bib.bib1" title="" class="ltx_ref">2020</a>; Lee and Kim, <a href="#bib.bib2" title="" class="ltx_ref">2025</a>)</cite>. Last sentence.</p></div>',
        )
        entry, contexts = extract_contexts(page(body, REFS), TARGET)
        self.assertEqual(entry["ids"], ["bib.bib2"])
        self.assertEqual(len(contexts), 1)
        c = contexts[0]
        self.assertEqual((c.match, c.section, c.co_cited, c.in_float), ("linked", "2 Related Work", 1, False))
        self.assertEqual(c.sentence, "Prior work is fast (Smith, 2020; <TARGET>Lee and Kim, 2025</TARGET>).")
        self.assertEqual((c.before, c.after), ("First sentence.", "Last sentence."))

    def test_numbered_citation_in_a_group(self):
        body = section("Intro", '<p class="ltx_p">Reasoning models <cite class="ltx_cite">[<a href="#bib.bib2" class="ltx_ref">2</a>, <a href="#bib.bib1" class="ltx_ref">1</a>]</cite> are popular.</p>')
        _, contexts = extract_contexts(page(body, REFS), TARGET)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].sentence, "Reasoning models [<TARGET>2</TARGET>, 1] are popular.")
        self.assertEqual(contexts[0].co_cited, 1)

    def test_table_row_is_kept_whole_with_maths_as_latex(self):
        body = section(
            "Results",
            '<table class="ltx_tabular"><tr class="ltx_tr"><td class="ltx_td">Widget-X2 <cite class="ltx_cite">(Lee and Kim, <a href="#bib.bib2" class="ltx_ref">2025</a>)</cite></td>'
            '<td class="ltx_td">62.1<math alttext="\\pm" display="inline"><semantics><mo>±</mo><annotation encoding="application/x-tex">\\pm</annotation></semantics></math>0.6</td></tr></table>',
        )
        _, contexts = extract_contexts(page(body, REFS), TARGET)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].sentence, "Widget-X2 (<TARGET>Lee and Kim, 2025</TARGET>) 62.1\\pm0.6")
        self.assertTrue(contexts[0].in_float)

    def test_name_mention_without_a_citation(self):
        body = section("Results", '<p class="ltx_p">Our model beats Widget-X2 by two points. Nothing here.</p>')
        _, contexts = extract_contexts(page(body, REFS), TARGET)
        self.assertEqual([c.match for c in contexts], ["name"])
        self.assertEqual(contexts[0].sentence, "Our model beats <TARGET>Widget-X2</TARGET> by two points.")

    def test_preprint_and_published_version_listed_as_two_references(self):
        refs = REFS + bib("bib.bib3", "B. Lee and C. Kim. Widget-X2: a faster way to frobnicate. arXiv preprint arXiv:2501.00001, 2025.")
        body = section("Intro", '<p class="ltx_p">One <cite class="ltx_cite">[<a href="#bib.bib2" class="ltx_ref">2</a>]</cite>. Two <cite class="ltx_cite">[<a href="#bib.bib3" class="ltx_ref">3</a>]</cite>.</p>')
        entry, contexts = extract_contexts(page(body, refs), TARGET)
        self.assertEqual(entry["ids"], ["bib.bib2", "bib.bib3"])
        self.assertEqual(len(contexts), 2)

    def test_target_missing_from_the_reference_list(self):
        entry, contexts = extract_contexts(page(section("Intro", '<p class="ltx_p">Nothing.</p>'), bib("bib.bib1", "A. Smith. Other. 2020.")), TARGET)
        self.assertIsNone(entry)
        self.assertEqual(contexts, [])


if __name__ == "__main__":
    unittest.main()
