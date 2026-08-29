#!/usr/bin/env python3
"""Tests for ORS roster discovery from the published roster document.

The Tika-backed tests use a synthetic PDF built by the test fixture, so they
exercise the real extraction path without network access.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import acquire_ors_roster as roster  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "titles_chapters_roster.pdf"
TIKA_JAR = Path(__file__).resolve().parents[2] / "tika-app-2.8.0.jar"

ROSTER_TEXT = """OREGON REVISED STATUTES
2025 EDITION
TITLES AND CHAPTERS

TITLE 1 COURTS OF RECORD; COURT OFFICERS; JURIES
1 Courts and Judicial Districts
3 Circuit Courts
iv
TITLE 3 REMEDIES AND SPECIAL ACTIONS
36 Mediation and Arbitration
36A Collaborative Dispute Resolution
12
TITLE 27 PUBLIC FACILITIES, CONTRACTING AND INSURANCE
279A Public Contracting - General Provisions
646A Trade Regulation
"""


class ParseRosterTest(unittest.TestCase):
    def setUp(self):
        self.titles, self.chapters, self.unparsed = roster.parse_roster(ROSTER_TEXT)

    def test_titles_are_captured_with_their_names(self):
        self.assertEqual(
            [(item["titleNumber"], item["titleName"]) for item in self.titles],
            [
                ("1", "COURTS OF RECORD; COURT OFFICERS; JURIES"),
                ("3", "REMEDIES AND SPECIAL ACTIONS"),
                ("27", "PUBLIC FACILITIES, CONTRACTING AND INSURANCE"),
            ],
        )

    def test_chapters_carry_number_name_and_owning_title(self):
        by_number = {item["chapterNumber"]: item for item in self.chapters}
        self.assertEqual(by_number["1"]["chapterName"], "Courts and Judicial Districts")
        self.assertEqual(by_number["1"]["titleNumber"], "1")
        self.assertEqual(by_number["646A"]["titleNumber"], "27")

    def test_lettered_chapters_survive_and_sort_correctly(self):
        self.assertEqual(
            [item["chapterNumber"] for item in self.chapters],
            ["1", "3", "36", "36A", "279A", "646A"],
        )

    def test_page_numbers_are_not_mistaken_for_chapters(self):
        numbers = [item["chapterNumber"] for item in self.chapters]
        self.assertNotIn("12", numbers)
        self.assertEqual(self.unparsed, [])

    def test_each_chapter_gets_its_published_url(self):
        by_number = {item["chapterNumber"]: item for item in self.chapters}
        self.assertTrue(by_number["279A"]["sourceUrl"].endswith("/ors279A.html"))

    def test_a_chapter_label_prefix_is_accepted(self):
        _, parsed, _ = roster.parse_roster("Chapter 161 General Provisions")
        self.assertEqual(parsed[0]["chapterNumber"], "161")
        self.assertEqual(parsed[0]["chapterName"], "General Provisions")


class EditionYearTest(unittest.TestCase):
    def test_reads_the_edition_banner(self):
        self.assertEqual(roster.detect_edition_year(ROSTER_TEXT), 2025)

    def test_returns_none_when_no_edition_is_stated(self):
        self.assertIsNone(roster.detect_edition_year("TITLES AND CHAPTERS"))


@unittest.skipUnless(TIKA_JAR.exists() and shutil.which("java"), "tika jar or java missing")
class RosterCliTest(unittest.TestCase):
    """Exercises the real Tika extraction path against a synthetic PDF."""

    def test_a_roster_pdf_yields_titles_chapters_and_an_edition(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "roster.json"
            exit_code = roster.main([
                "--pdf-file", str(FIXTURE),
                "--tika-jar", str(TIKA_JAR),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["editionYear"], 2025)
            self.assertEqual(report["editionId"], "2025")
            self.assertEqual(report["chapterCount"], 9)
            self.assertEqual(report["titleCount"], 5)
            self.assertEqual(len(report["rosterSha256"]), 64)
            self.assertEqual(report["rosterBytes"], FIXTURE.stat().st_size)
            self.assertEqual(
                [item["chapterNumber"] for item in report["chapters"]],
                ["1", "3", "36", "36A", "161", "162", "279A", "279B", "646A"],
            )

    def test_a_document_that_is_not_a_pdf_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            not_pdf = root / "notes.txt"
            not_pdf.write_bytes(b"plain text, not a roster")
            report_path = root / "roster.json"
            exit_code = roster.main([
                "--pdf-file", str(not_pdf),
                "--tika-jar", str(TIKA_JAR),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertIn("not a PDF", report["error"])

    def test_a_missing_tika_jar_is_a_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "roster.json"
            exit_code = roster.main([
                "--pdf-file", str(FIXTURE),
                "--tika-jar", str(Path(tmp) / "absent.jar"),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertIn("error", report)


class EmptyRosterTest(unittest.TestCase):
    def test_a_roster_with_no_chapters_and_no_edition_reports_both_problems(self):
        titles, chapters, _ = roster.parse_roster("TITLES AND CHAPTERS\n")
        self.assertEqual(chapters, [])
        self.assertEqual(titles, [])
        self.assertIsNone(roster.detect_edition_year("TITLES AND CHAPTERS\n"))

    def test_text_diagnostics_are_bounded(self):
        text = "\n".join(f"line {index} " + "x" * 400 for index in range(200))
        diagnostics = roster.text_diagnostics(text)
        self.assertEqual(len(diagnostics["sampleLines"]), roster.MAX_SAMPLE_LINES)
        self.assertLessEqual(
            max(len(line) for line in diagnostics["sampleLines"]),
            roster.MAX_SAMPLE_LINE_CHARS,
        )


if __name__ == "__main__":
    unittest.main()
