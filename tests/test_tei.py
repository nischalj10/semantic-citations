"""Offline tests for citation-context extraction. Run: python -m unittest"""

import unittest

from semantic_citations.taxonomy import build_questions, cito_property
from semantic_citations.tei import Target, _expand_numbers, _wrap, extract_contexts

TARGET = Target(title="Widget-X2: A Faster Way to Frobnicate", arxiv_id="2501.00001")


def tei(body: str, refs: str) -> str:
    return f"""<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>{body}</body>
    <back><div type="references"><listBibl>{refs}</listBibl></div></back></text></TEI>"""


def bib(xml_id: str, title: str, surname: str, year: str) -> str:
    return f"""<biblStruct xml:id="{xml_id}"><analytic><title level="a">{title}</title>
    <author><persName><forename>A</forename><surname>{surname}</surname></persName></author></analytic>
    <monogr><imprint><date when="{year}"/></imprint></monogr></biblStruct>"""


REFS = bib("b0", "Something Unrelated", "Smith", "2020") + bib("b1", "Widget-x2: A faster way to frobnicate", "Lee", "2025")


class Helpers(unittest.TestCase):
    def test_expand_numbers(self):
        self.assertEqual(_expand_numbers("13;14;15"), [13, 14, 15])
        self.assertEqual(_expand_numbers("[10-12, 20]"), [10, 11, 12, 20])
        self.assertEqual(_expand_numbers("Lee et al., 2025"), [])

    def test_wrap_keeps_punctuation_outside(self):
        self.assertEqual(_wrap("(Lee et al., 2025;"), "(<TARGET>Lee et al., 2025</TARGET>;")
        self.assertEqual(_wrap(", Lee et al., 2025"), ", <TARGET>Lee et al., 2025</TARGET>")
        self.assertEqual(_wrap("[2]"), "[<TARGET>2</TARGET>]")

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
    def test_linked_citation_with_neighbours_and_cocitation(self):
        body = """<div><head n="2">Related Work</head><p>
        <s>First sentence.</s>
        <s>Prior work is fast <ref type="bibr" target="#b0">(Smith, 2020;</ref> <ref type="bibr" target="#b1">Lee et al., 2025)</ref>.</s>
        <s>Last sentence.</s></p></div>"""
        entry, contexts = extract_contexts(tei(body, REFS), TARGET)
        self.assertEqual(entry.number, 2)
        self.assertEqual(len(contexts), 1)
        c = contexts[0]
        self.assertEqual((c.match, c.section, c.co_cited), ("linked", "2 Related Work", 1))
        self.assertIn("<TARGET>Lee et al., 2025</TARGET>)", c.sentence)
        self.assertEqual((c.before, c.after), ("First sentence.", "Last sentence."))

    def test_unlinked_numeric_marker(self):
        body = """<div><head>Intro</head><p>
        <s>See <ref type="bibr" target="#b0">1</ref> for details.</s>
        <s>Reasoning models <ref type="bibr">2;3;4</ref> are popular.</s></p></div>"""
        refs = REFS + bib("b2", "Third", "Kim", "2021") + bib("b3", "Fourth", "Park", "2022")
        _, contexts = extract_contexts(tei(body, refs), TARGET)
        self.assertEqual(len(contexts), 1)
        self.assertEqual((contexts[0].match, contexts[0].co_cited), ("marker", 2))
        self.assertIn("<TARGET>2</TARGET>;3;4", contexts[0].sentence)

    def test_unlinked_author_year_marker(self):
        body = """<div><head>Intro</head><p><s>Rewards are static <ref type="bibr">[Lee et al., 2025</ref><ref type="bibr">, Kim, 2021]</ref>.</s></p></div>"""
        _, contexts = extract_contexts(tei(body, REFS), TARGET)
        self.assertEqual(contexts[0].match, "marker")
        self.assertIn("[<TARGET>Lee et al., 2025</TARGET>", contexts[0].sentence)

    def test_name_mention_without_citation(self):
        body = """<div><head>Results</head><p><s>Our model beats Widget-X2 by two points.</s><s>Nothing here.</s></p></div>"""
        _, contexts = extract_contexts(tei(body, REFS), TARGET)
        self.assertEqual([c.match for c in contexts], ["name"])
        self.assertIn("<TARGET>Widget-X2</TARGET>", contexts[0].sentence)

    def test_not_in_reference_list(self):
        entry, contexts = extract_contexts(tei("<div><p><s>Nothing.</s></p></div>", bib("b0", "Other", "Smith", "2020")), TARGET)
        self.assertIsNone(entry)
        self.assertEqual(contexts, [])


if __name__ == "__main__":
    unittest.main()
