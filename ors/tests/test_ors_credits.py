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
    def test_a_bare_special_session_marker_records_ordinal_one(self):
        # Recorded in FINDINGS.md against chapter 1. The pre-2000s convention
        # names no ordinal, so it is recorded as special session 1.
        result = credits.parse_source_credit(
            "[1981 s.s. c.1 §3; 1995 c.658 §7; 1995 c.781 §3; 2013 c.155 §2]"
        )
        first, rest = result["citations"][0], result["citations"][1:]
        self.assertEqual(first["specialSession"], 1)
        self.assertEqual(first["sessionYear"], 1981)
        self.assertEqual(first["sessionLawChapter"], 1)
        self.assertTrue(all(c["specialSession"] is None for c in rest))

    def test_a_numbered_special_session_records_its_ordinal(self):
        # Real forms surfaced by the unparsed-segment diagnostic against
        # chapters 1 and 90: unlike the 1981 form, these name which special
        # session, with no space before the digit.
        first = credits.parse_source_credit("[2002 s.s.1 c.10 §7]")["citations"][0]
        self.assertEqual(first["specialSession"], 1)
        self.assertEqual(first["sessionYear"], 2002)
        self.assertEqual(first["sessionLawChapter"], 10)

        third = credits.parse_source_credit("[2020 s.s.3 c.3 §11]")["citations"][0]
        self.assertEqual(third["specialSession"], 3)
        self.assertEqual(third["sessionYear"], 2020)
        self.assertEqual(third["sessionLawChapter"], 3)
        self.assertEqual(third["sessionLawSection"], "11")


class PluralSectionCitationTest(unittest.TestCase):
    """A doubled section mark cites more than one section: "§§2,3"."""

    def test_a_comma_list_becomes_one_row_per_section(self):
        result = credits.parse_source_credit("[2013 c.154 §§2,3]")
        self.assertEqual(len(result["citations"]), 2)
        self.assertEqual(
            [c["sessionLawSection"] for c in result["citations"]], ["2", "3"]
        )
        # Both rows share the year, chapter and the full original segment, so
        # each still traces back to the one printed citation that named it.
        self.assertTrue(all(c["sessionYear"] == 2013 for c in result["citations"]))
        self.assertTrue(all(c["sessionLawChapter"] == 154 for c in result["citations"]))
        self.assertTrue(
            all(c["rawSegment"] == "2013 c.154 §§2,3" for c in result["citations"])
        )

    def test_a_lettered_section_survives_inside_a_comma_list(self):
        # Real form: "1999 c.676 §§7,7a".
        result = credits.parse_source_credit("[1999 c.676 §§7,7a]")
        self.assertEqual(
            [c["sessionLawSection"] for c in result["citations"]], ["7", "7a"]
        )

    def test_three_sections_in_one_doubled_citation(self):
        result = credits.parse_source_credit("[2013 c.154 §§2,3,4]")
        self.assertEqual(
            [c["sessionLawSection"] for c in result["citations"]], ["2", "3", "4"]
        )


class TrailingAnnotationTest(unittest.TestCase):
    def test_a_parenthetical_annotation_does_not_block_the_citation(self):
        # Real form against chapter 1: the citation is still fully usable;
        # the annotation is kept in the raw segment but not otherwise modeled.
        result = credits.parse_source_credit(
            "[2001 c.823 §25 (enacted in lieu of 8.172)]"
        )
        citation = result["citations"][0]
        self.assertEqual(citation["sessionYear"], 2001)
        self.assertEqual(citation["sessionLawChapter"], 823)
        self.assertEqual(citation["sessionLawSection"], "25")
        self.assertIn("enacted in lieu of 8.172", citation["rawSegment"])
        self.assertEqual(result["unparsedSegments"], [])


class ReenactedActionTest(unittest.TestCase):
    def test_reenacted_by_maps_to_the_schema_enacted_action(self):
        # SCHEMA.md's action set has no "reenacted" value; the keyword states
        # this session law (re-)established the section, which "enacted"
        # already means there.
        result = credits.parse_source_credit("[reenacted by 1997 c.196 §3]")
        citation = result["citations"][0]
        self.assertEqual(citation["action"], "enacted")
        self.assertEqual(citation["sessionYear"], 1997)


class RenumberNoteWithYearTest(unittest.TestCase):
    def test_a_renumber_note_naming_a_year_is_still_a_bare_reference(self):
        # Real form: "renumbered 1.179 in 2025". The trailing year describes
        # when the renumbering happened, not a session law that did it, so it
        # is discarded rather than parsed as a session-year citation.
        result = credits.parse_source_credit("[renumbered 1.179 in 2025]")
        self.assertEqual(result["renumberReferences"], ["1.179"])
        self.assertEqual(result["citations"], [])


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


class AndJoinedCitationTest(unittest.TestCase):
    def test_two_citations_joined_by_and_both_parse(self):
        # Real form against a sample chapter: no semicolon, joined by "and".
        result = credits.parse_source_credit("[2009 c.431 §6 and 2009 c.816 §15]")
        self.assertEqual(
            [(c["sessionYear"], c["sessionLawChapter"], c["sessionLawSection"])
             for c in result["citations"]],
            [(2009, 431, "6"), (2009, 816, "15")],
        )
        self.assertEqual(result["unparsedSegments"], [])

    def test_and_joined_citations_with_a_lettered_section(self):
        result = credits.parse_source_credit("[1999 c.603 §2b and 1999 c.676 §4]")
        self.assertEqual(
            [c["sessionLawSection"] for c in result["citations"]], ["2b", "4"]
        )

    def test_the_word_and_inside_an_unparseable_segment_does_not_split_it(self):
        # A segment that merely contains "and" but is not two citations joined
        # by it must still be reported, not silently split into nonsense.
        result = credits.parse_source_credit("[see also chapter 90 and chapter 91]")
        self.assertEqual(result["citations"], [])
        self.assertEqual(
            result["unparsedSegments"], ["see also chapter 90 and chapter 91"]
        )


class DerivedFromActionTest(unittest.TestCase):
    def test_derived_from_maps_to_the_schema_enacted_action(self):
        result = credits.parse_source_credit("[Derived from 1983 c.740 §1]")
        citation = result["citations"][0]
        self.assertEqual(citation["action"], "enacted")
        self.assertEqual(citation["sessionYear"], 1983)
        self.assertEqual(citation["sessionLawChapter"], 740)


class SubsectionScopedCitationTest(unittest.TestCase):
    def test_a_subsection_enacted_as_prefix_still_yields_the_citation(self):
        # The subsection scoping is read past, not modeled (see SCHEMA.md's
        # deferred list and the module docstring in ors_credits.py).
        result = credits.parse_source_credit(
            "[subsection (3) enacted as 1961 c.150 §5]"
        )
        citation = result["citations"][0]
        self.assertEqual(citation["action"], "enacted")
        self.assertEqual(citation["sessionYear"], 1961)
        self.assertEqual(citation["sessionLawChapter"], 150)
        self.assertEqual(citation["sessionLawSection"], "5")

    def test_formerly_with_a_subsection_range_qualifier(self):
        result = credits.parse_source_credit(
            "[Formerly subsections (1) to (3) of 192.450]"
        )
        self.assertEqual(result["formerlyReferences"], ["192.450"])
        self.assertEqual(result["citations"], [])

    def test_a_single_section_with_a_subsection_list_is_one_citation(self):
        # Distinct from the plural-SECTION "§§2,3" case: here "(2),(3)" are
        # subsections of the one cited section, §8, not additional sections.
        result = credits.parse_source_credit("[1977 c.517 §8(2),(3)]")
        self.assertEqual(len(result["citations"]), 1)
        citation = result["citations"][0]
        self.assertEqual(citation["sessionYear"], 1977)
        self.assertEqual(citation["sessionLawChapter"], 517)
        self.assertEqual(citation["sessionLawSection"], "8")


class BracketStrippingTest(unittest.TestCase):
    def test_brackets_are_optional_on_input(self):
        with_brackets = credits.parse_source_credit("[1971 c.743 §1]")
        without_brackets = credits.parse_source_credit("1971 c.743 §1")
        self.assertEqual(with_brackets["citations"], without_brackets["citations"])


if __name__ == "__main__":
    unittest.main()
