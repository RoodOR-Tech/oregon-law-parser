#!/usr/bin/env python3
"""Tests for shared ORS chapter-number handling."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ors_chapters as chapters  # noqa: E402


class ChapterNumberTest(unittest.TestCase):
    def test_leading_zeros_are_stripped_and_letters_upper_cased(self):
        self.assertEqual(chapters.parse_chapter_number("001"), "1")
        self.assertEqual(chapters.parse_chapter_number("036a"), "36A")
        self.assertEqual(chapters.parse_chapter_number(" 279B "), "279B")

    def test_a_section_number_is_not_a_chapter_number(self):
        self.assertIsNone(chapters.parse_chapter_number("161.005"))
        self.assertIsNone(chapters.parse_chapter_number("bogus"))
        self.assertIsNone(chapters.parse_chapter_number(""))

    def test_sort_key_orders_chapters_the_way_the_statute_book_does(self):
        numbers = ["279B", "1", "97", "36A", "36", "279A", "161", "646A"]
        self.assertEqual(
            sorted(numbers, key=chapters.chapter_sort_key),
            ["1", "36", "36A", "97", "161", "279A", "279B", "646A"],
        )

    def test_unparseable_chapter_number_sorts_last_instead_of_raising(self):
        self.assertGreater(
            chapters.chapter_sort_key("bogus"), chapters.chapter_sort_key("838")
        )

    def test_file_stem_zero_pads_and_preserves_the_letter(self):
        self.assertEqual(chapters.chapter_file_stem("1"), "001")
        self.assertEqual(chapters.chapter_file_stem("36A"), "036A")
        self.assertEqual(chapters.chapter_file_stem("279A"), "279A")

    def test_chapter_url_matches_the_confirmed_published_pattern(self):
        self.assertEqual(
            chapters.chapter_url("161"),
            "https://www.oregonlegislature.gov/bills_laws/ors/ors161.html",
        )
        self.assertEqual(
            chapters.chapter_url("279A"),
            "https://www.oregonlegislature.gov/bills_laws/ors/ors279A.html",
        )

    def test_invalid_chapter_number_raises_for_url_construction(self):
        with self.assertRaises(ValueError):
            chapters.chapter_file_stem("161.005")


if __name__ == "__main__":
    unittest.main()
