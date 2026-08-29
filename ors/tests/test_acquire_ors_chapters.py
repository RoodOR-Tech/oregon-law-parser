#!/usr/bin/env python3
"""Offline tests for ORS chapter discovery and acquisition.

Every test runs without network egress, using synthetic index pages, so the
suite is runnable on a development machine that cannot reach the Oregon
Legislature site.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import acquire_ors_chapters as acquire  # noqa: E402


SYNTHETIC_INDEX = """
<html><head><title>Oregon Revised Statutes</title></head>
<body>
  <h1>2025 Edition</h1>
  <ul>
    <li><a href="/bills_laws/ors/ors001.html">Chapter 1 &mdash; Courts</a></li>
    <li><a href="/bills_laws/ors/ors036.html">Chapter 36</a></li>
    <li><a href="/bills_laws/ors/ors036A.html">Chapter 36A</a></li>
    <li><a href="/bills_laws/ors/ors161.html">Chapter 161</a></li>
    <li><a href="/bills_laws/ors/ors279A.html">Chapter 279A</a></li>
    <li><a href="/bills_laws/ors/ors279B.html">Chapter 279B</a></li>
    <li><a href="/bills_laws/ors/ors001.html">Chapter 1 (duplicate link)</a></li>
    <li><a href="/bills_laws/lawsstatutes/2023orlaw0001.pdf">Not a chapter</a></li>
    <li><a href="/bills_laws/ors/2023.pdf">Chapter range reference, not a chapter</a></li>
  </ul>
</body></html>
"""


class ChapterNumberTest(unittest.TestCase):
    def test_leading_zeros_are_stripped_and_letters_upper_cased(self):
        self.assertEqual(acquire.normalize_chapter_number("001", ""), "1")
        self.assertEqual(acquire.normalize_chapter_number("036", "a"), "36A")
        self.assertEqual(acquire.normalize_chapter_number("279", "B"), "279B")

    def test_sort_key_orders_chapters_the_way_the_statute_book_does(self):
        numbers = ["279B", "1", "97", "36A", "36", "279A", "161"]
        ordered = sorted(numbers, key=acquire.chapter_sort_key)
        self.assertEqual(ordered, ["1", "36", "36A", "97", "161", "279A", "279B"])

    def test_unparseable_chapter_number_sorts_last_instead_of_raising(self):
        self.assertGreater(acquire.chapter_sort_key("bogus"), acquire.chapter_sort_key("838"))

    def test_file_stem_round_trips_to_the_published_url(self):
        self.assertEqual(acquire.chapter_file_stem("1"), "001")
        self.assertEqual(acquire.chapter_file_stem("36A"), "036A")
        self.assertEqual(acquire.chapter_file_stem("279A"), "279A")
        self.assertEqual(
            acquire.chapter_url("161"),
            "https://www.oregonlegislature.gov/bills_laws/ors/ors161.html",
        )

    def test_invalid_chapter_number_raises_for_url_construction(self):
        with self.assertRaises(ValueError):
            acquire.chapter_file_stem("161.005")


class ParseChapterIndexTest(unittest.TestCase):
    def test_extracts_chapters_deduplicated_and_in_order(self):
        chapters = acquire.parse_chapter_index(SYNTHETIC_INDEX, acquire.DEFAULT_INDEX_URL)
        self.assertEqual(
            [item["chapterNumber"] for item in chapters],
            ["1", "36", "36A", "161", "279A", "279B"],
        )

    def test_relative_hrefs_resolve_against_the_index_url(self):
        chapters = acquire.parse_chapter_index(SYNTHETIC_INDEX, acquire.DEFAULT_INDEX_URL)
        by_number = {item["chapterNumber"]: item for item in chapters}
        self.assertEqual(
            by_number["161"]["sourceUrl"],
            "https://www.oregonlegislature.gov/bills_laws/ors/ors161.html",
        )

    def test_non_chapter_links_are_ignored(self):
        chapters = acquire.parse_chapter_index(SYNTHETIC_INDEX, acquire.DEFAULT_INDEX_URL)
        urls = " ".join(item["sourceUrl"] for item in chapters)
        self.assertNotIn("2023orlaw0001", urls)
        self.assertNotIn("ors/2023.pdf", urls)

    def test_absolute_hrefs_and_upper_case_markup_are_handled(self):
        markup = (
            '<A HREF="https://www.oregonlegislature.gov/bills_laws/ORS/ORS090.html">90</A>'
        )
        chapters = acquire.parse_chapter_index(markup, acquire.DEFAULT_INDEX_URL)
        self.assertEqual([item["chapterNumber"] for item in chapters], ["90"])

    def test_empty_index_yields_no_chapters_rather_than_a_guessed_range(self):
        self.assertEqual(acquire.parse_chapter_index("<html></html>", acquire.DEFAULT_INDEX_URL), [])


class EditionYearTest(unittest.TestCase):
    def test_reads_the_advertised_edition_year(self):
        self.assertEqual(acquire.detect_edition_year(SYNTHETIC_INDEX), 2025)

    def test_returns_none_when_the_page_states_no_year(self):
        self.assertIsNone(acquire.detect_edition_year("<html><body>Statutes</body></html>"))

    def test_prefers_the_latest_advertised_year(self):
        markup = "<p>2023 Edition</p><p>2025 Edition</p>"
        self.assertEqual(acquire.detect_edition_year(markup), 2025)


class SourceFormatTest(unittest.TestCase):
    def test_pdf_magic_bytes_win_over_the_url_suffix(self):
        self.assertEqual(acquire.source_format("https://x.test/ors001.html", b"%PDF-1.7"), "pdf")

    def test_html_is_detected_from_the_doctype(self):
        self.assertEqual(
            acquire.source_format("https://x.test/ors001.html", b"<!DOCTYPE html><html>"),
            "html",
        )

    def test_unknown_binary_at_an_unknown_suffix_is_rejected(self):
        self.assertIsNone(acquire.source_format("https://x.test/ors001.bin", b"\x00\x01\x02"))


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.chapters = acquire.parse_chapter_index(SYNTHETIC_INDEX, acquire.DEFAULT_INDEX_URL)

    def test_requested_chapters_are_normalized_and_ordered(self):
        chosen = acquire.selected_chapters(self.chapters, ["279a", "1"], None)
        self.assertEqual([item["chapterNumber"] for item in chosen], ["1", "279A"])

    def test_requesting_an_unpublished_chapter_is_an_error_not_a_silent_skip(self):
        with self.assertRaises(ValueError) as caught:
            acquire.selected_chapters(self.chapters, ["999"], None)
        self.assertIn("999", str(caught.exception))

    def test_malformed_request_is_rejected(self):
        with self.assertRaises(ValueError):
            acquire.selected_chapters(self.chapters, ["161.005"], None)

    def test_limit_truncates_in_statute_book_order(self):
        chosen = acquire.selected_chapters(self.chapters, [], 3)
        self.assertEqual([item["chapterNumber"] for item in chosen], ["1", "36", "36A"])


class IndexOnlyCliTest(unittest.TestCase):
    def test_index_only_run_reports_the_roster_without_network_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_file = root / "index.html"
            index_file.write_text(SYNTHETIC_INDEX)
            report_path = root / "report.json"
            exit_code = acquire.main([
                "--index-only",
                "--index-file", str(index_file),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["stage"], "index")
            self.assertEqual(report["indexSource"], "file")
            self.assertEqual(report["editionYear"], 2025)
            self.assertEqual(report["editionId"], "2025")
            self.assertEqual(report["discoveredChapterCount"], 6)
            self.assertEqual(len(report["indexSha256"]), 64)
            self.assertEqual(report["indexBytes"], len(SYNTHETIC_INDEX.encode()))

    def test_an_index_with_no_chapters_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_file = root / "index.html"
            index_file.write_text("<html><body>maintenance</body></html>")
            report_path = root / "report.json"
            exit_code = acquire.main([
                "--index-only",
                "--index-file", str(index_file),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertIn("no chapter links", report["error"])


if __name__ == "__main__":
    unittest.main()
