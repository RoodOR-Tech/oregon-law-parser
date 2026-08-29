#!/usr/bin/env python3
"""Tests for parsing ORS bracketed source credits.

Every sample here is a real credit string recorded in FINDINGS.md, drawn from
the sample chapters, not invented for the test.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ors_credits as credits  # noqa: E402


class PlainCitationTest(unittest.TestCase):
    def test_a_single_citation_has_no_stated_action(self):
        result = credits.parse_source_credit("[1971 c.743 §1]")
        self.assertEqual(len(result["citations"]), 1)
        citation = result["citations"][0]
        self.assertEqual(citation["action"], "unspecified")
        self.assertEqual(citation["sessionYear"], 1971)
        self.assertEqual(citation["sessionLawChapter"], 743)
        self.assertEqual(citation["sessionLawSection"], "1")
        self.assertIsNone(citation["specialSession"])

    def test_a_multi_session_credit_yields_one_row_per_citation_in_order(self):
        result = credits.parse_source_credit(
            "[1971 c.743 §3; 1973 c.836 §339; 2025 c.161 §4]"
        )
        self.assertEqual(
            [(c["sessionYear"], c["sessionLawChapter"], c["sessionLawSection"])
             for c in result["citations"]],
            [(1971, 743, "3"), (1973, 836, "339"), (2025, 161, "4")],
        )

    def test_an_eight_citation_credit_parses_completely(self):
        # Recorded in FINDINGS.md against chapter 192.
        raw = (
            "[1961 c.160 §2; 1965 c.302 §1; 1983 c.620 §11; 1989 c.16 §1; "
            "1999 c.55 §1; 1999 c.140 §1; 2011 c.645 §1; 2023 c.35 §2]"
        )
        result = credits.parse_source_credit(raw)
        self.assertEqual(len(result["citations"]), 8)
        self.assertEqual(result["unparsedSegments"], [])

    def test_a_citation_with_no_section_number_still_parses(self):
        result = credits.parse_source_credit("[1971 c.743]")
        self.assertEqual(result["citations"][0]["sessionLawChapter"], 743)
        self.assertIsNone(result["citations"][0]["sessionLawSection"])


class ActionKeywordTest(unittest.TestCase):
    def test_a_bare_repealed_by_stub_credit(self):
        result = credits.parse_source_credit("[Repealed by 1973 c.794 §34]")
        citation = result["citations"][0]
        self.assertEqual(citation["action"], "repealed")
        self.assertEqual(citation["sessionYear"], 1973)
        self.assertEqual(citation["sessionLawChapter"], 794)

    def test_each_segment_carries_its_own_action(self):
        # "Amended by ...; repealed by ..." -- two citations, two actions.
        # The final segment is a repeal even though an amendment precedes it.
        result = credits.parse_source_credit(
            "[Amended by 1961 c.160 §4; repealed by 1973 c.794 §34]"
        )
        self.assertEqual(
            [(c["action"], c["sessionYear"]) for c in result["citations"]],
            [("amended", 1961), ("repealed", 1973)],
        )

    def test_the_action_keyword_is_case_insensitive(self):
        result = credits.parse_source_credit("[REPEALED BY 1973 c.794 §34]")
        self.assertEqual(result["citations"][0]["action"], "repealed")


class NonCitationFormTest(unittest.TestCase):
    def test_formerly_is_not_a_citation(self):
        result = credits.parse_source_credit(
            "[Formerly 646.185; repealed by 2009 c.170 §4]"
        )
        self.assertEqual(result["formerlyReferences"], ["646.185"])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["action"], "repealed")
        self.assertEqual(result["citations"][0]["sessionYear"], 2009)

    def test_a_bare_renumbering_destination_is_not_a_citation(self):
        result = credits.parse_source_credit("[Renumbered 161.045]")
        self.assertEqual(result["renumberReferences"], ["161.045"])
        self.assertEqual(result["citations"], [])

    def test_formerly_alone_produces_no_citations(self):
        result = credits.parse_source_credit("[Formerly 646.185]")
        self.assertEqual(result["formerlyReferences"], ["646.185"])
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["unparsedSegments"], [])


class SpecialSessionTest(unittest.TestCase):
    def test_a_special_session_marker_is_recorded(self):
        # Recorded in FINDINGS.md against chapter 1.
        result = credits.parse_source_credit(
            "[1981 s.s. c.1 §3; 1995 c.658 §7; 1995 c.781 §3; 2013 c.155 §2]"
        )
        first, rest = result["citations"][0], result["citations"][1:]
        self.assertEqual(first["specialSession"], 1)
        self.assertEqual(first["sessionYear"], 1981)
        self.assertEqual(first["sessionLawChapter"], 1)
        self.assertTrue(all(c["specialSession"] is None for c in rest))


class UnparsedSegmentTest(unittest.TestCase):
    def test_an_unrecognized_segment_is_reported_not_dropped(self):
        result = credits.parse_source_credit("[see also chapter 90]")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["unparsedSegments"], ["see also chapter 90"])

    def test_one_bad_segment_does_not_block_the_others_in_the_same_credit(self):
        result = credits.parse_source_credit(
            "[1971 c.743 §1; see also chapter 90; 1973 c.836 §2]"
        )
        self.assertEqual(len(result["citations"]), 2)
        self.assertEqual(result["unparsedSegments"], ["see also chapter 90"])


class BracketStrippingTest(unittest.TestCase):
    def test_brackets_are_optional_on_input(self):
        with_brackets = credits.parse_source_credit("[1971 c.743 §1]")
        without_brackets = credits.parse_source_credit("1971 c.743 §1")
        self.assertEqual(with_brackets["citations"], without_brackets["citations"])


if __name__ == "__main__":
    unittest.main()
