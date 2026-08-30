#!/usr/bin/env python3
"""Tests for the increment-3 editorial-note candidate measurement pass.

The real fragment is what CI reported for 2025-1.002 as a cross-reference
candidate for "chapter 88", printed just after that section's own bracketed
credit: "... 2025 c.256 §6] Note: Sections 3 and 4, chapter 88, Oregon
Laws 2025, provide: Sec. 3. No...". See ors_section_notes.py's module
docstring for why this pass measures rather than extracts.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ors_section_notes as notes  # noqa: E402


class EmptyBodyTest(unittest.TestCase):
    def test_no_body_text_yields_no_candidates(self):
        self.assertEqual(notes.find_editorial_note_candidates(""), [])
        self.assertEqual(notes.find_editorial_note_candidates(None), [])


class NoteIntroducerTest(unittest.TestCase):
    def test_the_real_fragment_is_found_as_a_note_candidate(self):
        # Real fragment observed for 2025-1.002 in CI's cross-reference
        # candidate report.
        body = (
            "[2025 c.256 §6] Note: Sections 3 and 4, chapter 88, "
            "Oregon Laws 2025, provide: Sec. 3. Notwithstanding any other "
            "law, this section applies to..."
        )
        result = notes.find_editorial_note_candidates(body)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["introducer"], "Note:")
        self.assertIn("Sections 3 and 4, chapter 88", result[0]["context"])

    def test_a_plural_notes_introducer_is_also_found(self):
        result = notes.find_editorial_note_candidates("Notes: See also ORS 1.003.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["introducer"], "Notes:")

    def test_more_than_one_note_is_found_in_reading_order(self):
        body = "Note: First note here. Note: Second note here."
        result = notes.find_editorial_note_candidates(body)
        self.assertEqual(len(result), 2)
        self.assertIn("First note", result[0]["context"])
        self.assertIn("Second note", result[1]["context"])

    def test_context_is_capped_and_starts_at_the_introducer(self):
        body = "Note: " + ("x" * 500)
        result = notes.find_editorial_note_candidates(body)
        self.assertTrue(result[0]["context"].startswith("Note:"))
        self.assertLessEqual(len(result[0]["context"]), 6 + notes.CONTEXT_RADIUS)

    def test_note_glued_to_a_preceding_word_is_not_matched(self):
        # "SeeNote:" has no word boundary before "Note", so it is not a
        # real introducer -- just the substring "Note:" inside a longer word.
        result = notes.find_editorial_note_candidates("SeeNote: anything.")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
