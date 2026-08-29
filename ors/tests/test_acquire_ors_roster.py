#!/usr/bin/env python3
"""Tests for reading the published ORS table of titles.

The text below is transcribed from what Tika extracted from the real
ORS_TitlesChapters.pdf, so the parser is tested against the layout the
document actually has rather than an assumed one.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import acquire_ors_roster as roster  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "table_of_titles.pdf"
TIKA_JAR = Path(__file__).resolve().parents[2] / "tika-app-2.8.0.jar"

REAL_TEXT = """TABLE OF TITLES
xxxv
COURTS
ORCP
Volume 1
Title 1 Courts of Record; Court Officers; Juries – Chs. 1-10
2 Procedure in Civil Proceedings – Chs. 12-25
3 Remedies and Special Actions and Proceedings – Chs. 28-37
4 Evidence and Witnesses – Chs. 40-45
5 Small Claims Department of Circuit Court – Ch. 46
6 Justice Courts – Chs. 51-55
BUSINESS
ORGANIZATIONS
COMMERCIAL
CODE
Volume 2
Title 7 Corporations and Partnerships – Chs. 56-70
8 Commercial Transactions – Chs. 71-84
9 Mortgages and Liens – Chs. 86-88
LANDLORD-
TENANT
DOMESTIC
RELATIONS
PROBATE
Volume 3
Title 10 Property Rights and Transactions – Chs. 90-105
11 Domestic Relations – Chs. 106-110
12 Probate Law – Chs. 111-119
13 Protective Proceedings; Powers of Attorney; Trusts – Chs. 124-130
CRIMINAL
PROCEDURE
CRIMES
Volume 4
Title 14 Procedure in Criminal Matters Generally – Chs. 131-153
16 Crimes and Punishments – Chs. 161-169
"""


class TableOfTitlesTest(unittest.TestCase):
    def setUp(self):
        self.volumes, self.titles, self.unparsed = roster.parse_table_of_titles(REAL_TEXT)

    def test_volumes_are_captured_with_the_span_of_their_titles(self):
        self.assertEqual([item["volumeNumber"] for item in self.volumes], [1, 2, 3, 4])
        by_number = {item["volumeNumber"]: item for item in self.volumes}
        self.assertEqual(by_number[1]["firstChapter"], "1")
        self.assertEqual(by_number[1]["lastChapter"], "55")
        self.assertEqual(by_number[1]["titleCount"], 6)

    def test_titles_after_the_first_in_a_volume_omit_the_word_title(self):
        # "Title 1 ..." then bare "2 ...", "3 ...". A pattern that reads a bare
        # leading number as a chapter misreads every one of these.
        numbers = [item["titleNumber"] for item in self.titles]
        self.assertEqual(numbers[:6], ["1", "2", "3", "4", "5", "6"])
        self.assertEqual(len(self.titles), 15)

    def test_each_title_carries_its_name_and_owning_volume(self):
        by_number = {item["titleNumber"]: item for item in self.titles}
        self.assertEqual(by_number["16"]["titleName"], "Crimes and Punishments")
        self.assertEqual(by_number["16"]["volumeNumber"], 4)
        self.assertEqual(by_number["13"]["titleName"],
                         "Protective Proceedings; Powers of Attorney; Trusts")

    def test_a_singular_chapter_range_becomes_a_one_chapter_span(self):
        by_number = {item["titleNumber"]: item for item in self.titles}
        self.assertEqual(by_number["5"]["firstChapter"], "46")
        self.assertEqual(by_number["5"]["lastChapter"], "46")

    def test_sidebar_labels_and_page_numbers_are_not_titles(self):
        names = [item["titleName"] for item in self.titles]
        self.assertNotIn("ORCP", names)
        self.assertNotIn("PROBATE", names)
        # "LANDLORD-" contains a hyphen but no chapter range, so it is skipped.
        self.assertFalse(any("LANDLORD" in (name or "") for name in names))
        self.assertEqual(self.unparsed, [])


class ChapterRangeTest(unittest.TestCase):
    def test_a_span_and_a_single_chapter_both_parse(self):
        self.assertEqual(
            roster.parse_chapter_range("1-10"),
            {
                "firstChapter": "1", "lastChapter": "10",
                "firstChapterSortKey": "000001 ", "lastChapterSortKey": "000010 ",
            },
        )
        span = roster.parse_chapter_range("46")
        self.assertEqual(span["firstChapter"], "46")
        self.assertEqual(span["lastChapter"], "46")

    def test_a_lettered_endpoint_parses(self):
        span = roster.parse_chapter_range("279A-279C")
        self.assertEqual((span["firstChapter"], span["lastChapter"]), ("279A", "279C"))

    def test_an_unparseable_range_returns_none(self):
        self.assertIsNone(roster.parse_chapter_range("various"))


class ChapterContainmentTest(unittest.TestCase):
    def setUp(self):
        _, self.titles, _ = roster.parse_table_of_titles(REAL_TEXT)

    def test_a_chapter_is_matched_to_its_title(self):
        self.assertEqual(roster.chapter_is_published("1", self.titles)["titleNumber"], "1")
        self.assertEqual(roster.chapter_is_published("161", self.titles)["titleNumber"], "16")
        self.assertEqual(roster.chapter_is_published("46", self.titles)["titleNumber"], "5")

    def test_a_lettered_chapter_falls_inside_a_numeric_range(self):
        self.assertEqual(roster.chapter_is_published("90A", self.titles)["titleNumber"], "10")

    def test_the_gaps_between_ranges_are_real_and_preserved(self):
        # Title 1 covers 1-10 and title 2 covers 12-25, so chapter 11 exists in
        # neither. Title 8 ends at 84 and title 9 begins at 86, so 85 does not
        # either. Those gaps are the document telling us the chapters are absent.
        self.assertIsNone(roster.chapter_is_published("11", self.titles))
        self.assertIsNone(roster.chapter_is_published("85", self.titles))
        self.assertIsNone(roster.chapter_is_published("999", self.titles))


@unittest.skipUnless(TIKA_JAR.exists() and shutil.which("java"), "tika jar or java missing")
class RosterCliTest(unittest.TestCase):
    """Exercises the real Tika extraction path against a synthetic PDF."""

    def test_the_document_yields_volumes_and_titles_but_claims_no_chapter_roster(self):
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
            self.assertEqual(report["volumeCount"], 5)
            self.assertEqual(report["titleCount"], 13)
            self.assertEqual(report["unparsedLineCount"], 0)
            # The document does not enumerate chapters and must not claim to.
            self.assertFalse(report["chapterRosterAvailable"])
            self.assertNotIn("chapters", report)
            self.assertEqual(len(report["rosterSha256"]), 64)

    def test_a_document_that_is_not_a_pdf_fails_before_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            not_pdf = root / "notes.txt"
            not_pdf.write_bytes(b"plain text, not a roster")
            report_path = root / "roster.json"
            self.assertEqual(roster.main([
                "--pdf-file", str(not_pdf),
                "--tika-jar", str(TIKA_JAR),
                "--report", str(report_path),
            ]), 1)
            self.assertIn("not a PDF", json.loads(report_path.read_text())["error"])

    def test_a_missing_tika_jar_is_a_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "roster.json"
            self.assertEqual(roster.main([
                "--pdf-file", str(FIXTURE),
                "--tika-jar", str(Path(tmp) / "absent.jar"),
                "--report", str(report_path),
            ]), 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertIn("error", report)


class EmptyDocumentTest(unittest.TestCase):
    def test_a_document_with_no_titles_yields_nothing(self):
        volumes, titles, unparsed = roster.parse_table_of_titles("TABLE OF TITLES\nxxxv\n")
        self.assertEqual((volumes, titles, unparsed), ([], [], []))

    def test_a_title_line_with_an_unreadable_range_is_reported_not_dropped(self):
        text = "Volume 1\nTitle 1 Courts of Record – Chs. various\n"
        _, titles, unparsed = roster.parse_table_of_titles(text)
        self.assertEqual(titles, [])
        self.assertEqual(len(unparsed), 1)

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
