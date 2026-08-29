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
