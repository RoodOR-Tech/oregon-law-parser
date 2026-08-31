#!/usr/bin/env python3
"""Tests for the increment-4 cross-reference candidate measurement pass.

Samples here are drawn from real fragments already seen in an earlier
structure-probe sample for chapter 1 ("1.194 to 1.200"), plus synthetic
sentences shaped like ordinary statutory text for the forms not yet
observed in full (a bare section mention, a chapter mention). See
ors_cross_references.py's module docstring for why this pass is
deliberately generous rather than a finished extraction rule.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ors_cross_references as xref  # noqa: E402


class EmptyBodyTest(unittest.TestCase):
    def test_no_body_text_yields_no_candidates(self):
        self.assertEqual(xref.find_cross_reference_candidates(""), [])
        self.assertEqual(xref.find_cross_reference_candidates(None), [])


class RangeCandidateTest(unittest.TestCase):
    def test_a_real_range_is_found_as_one_candidate(self):
        # Real fragment observed in chapter 1's own structure-probe sample.
        result = xref.find_cross_reference_candidates("ORS 1.194 to 1.200 apply.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "range")
        self.assertEqual(result[0]["text"], "1.194 to 1.200")

    def test_a_ranges_two_endpoints_are_not_also_reported_as_bare_sections(self):
        result = xref.find_cross_reference_candidates("ORS 161.005 to 161.055 shall apply.")
        kinds = [item["kind"] for item in result]
        self.assertEqual(kinds, ["range"])


class SectionCandidateTest(unittest.TestCase):
    def test_a_bare_section_mention_is_found(self):
        result = xref.find_cross_reference_candidates("as provided in ORS 90.100 unless otherwise.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "section")
        self.assertEqual(result[0]["text"], "90.100")

    def test_more_than_one_bare_mention_is_found_in_reading_order(self):
        result = xref.find_cross_reference_candidates("See ORS 90.100 and ORS 90.200 for detail.")
        self.assertEqual([item["text"] for item in result], ["90.100", "90.200"])

    def test_context_surrounds_the_match(self):
        result = xref.find_cross_reference_candidates("as provided in ORS 90.100 unless otherwise noted.")
        self.assertIn("90.100", result[0]["context"])
        self.assertIn("provided in ORS", result[0]["context"])


class ChapterCandidateTest(unittest.TestCase):
    def test_a_chapter_mention_is_found(self):
        result = xref.find_cross_reference_candidates("as defined in ORS chapter 90.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "chapter")
        self.assertEqual(result[0]["text"], "chapter 90")

    def test_a_lettered_chapter_mention_is_found(self):
        result = xref.find_cross_reference_candidates("subject to ORS chapter 279A.")
        self.assertEqual(result[0]["text"], "chapter 279A")

    def test_a_session_law_chapter_mention_is_not_an_ors_chapter_candidate(self):
        # Real forms: a session-law chapter is not preceded by "ORS", unlike
        # every real ORS chapter mention observed so far.
        result = xref.find_cross_reference_candidates(
            "Note: Sections 3 and 4, chapter 88, Oregon Laws 2025, provide:"
        )
        self.assertEqual(result, [])

    def test_a_session_law_chapter_after_section_n_is_not_a_candidate(self):
        result = xref.find_cross_reference_candidates(
            "the amount specified in section 1 (6), chapter 705, Oregon Laws 2013"
        )
        self.assertEqual(result, [])

    def test_a_real_ors_chapter_mention_survives_alongside_a_session_law_one(self):
        # Real form: both shapes appear in the same sentence.
        result = xref.find_cross_reference_candidates(
            "bonds issued under ORS 271.390 or ORS chapter 287A to finance capital "
            "costs of the courthouse under section 10, chapter 685, Oregon Laws 2015"
        )
        chapter_candidates = [c for c in result if c["kind"] == "chapter"]
        self.assertEqual(len(chapter_candidates), 1)
        self.assertEqual(chapter_candidates[0]["text"], "chapter 287A")


class MixedCandidateOrderTest(unittest.TestCase):
    def test_candidates_of_different_kinds_stay_in_reading_order(self):
        result = xref.find_cross_reference_candidates(
            "See ORS 90.100, ORS chapter 161, and ORS 1.194 to 1.200 for detail."
        )
        self.assertEqual(
            [(item["kind"], item["text"]) for item in result],
            [("section", "90.100"), ("chapter", "chapter 161"), ("range", "1.194 to 1.200")],
        )


if __name__ == "__main__":
    unittest.main()
