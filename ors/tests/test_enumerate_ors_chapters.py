#!/usr/bin/env python3
"""Tests for verified chapter-roster enumeration.

Pure-function tests cover which integers a title's range walks and how a
digit family's letter probing is bounded. The end-to-end tests run the real
download path against a loopback HTTP server, the same pattern
test_acquisition_end_to_end.py uses for acquire_ors_chapters.py, so no test
here reaches the real Oregon Legislature site.
"""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import enumerate_ors_chapters as enumerate_chapters  # noqa: E402
import probe_ors_structure as probe  # noqa: E402
from ors_chapters import chapter_file_stem  # noqa: E402

CHAPTER_BODY = (
    "<html><body><p>Chapter {number}</p>"
    "<p><b>{number}.005 Short title.</b> Text of the section. [1971 c.743 &sect;1]</p>"
    "</body></html>"
)


def _title(number, name, volume, first, last):
    return {
        "titleNumber": number,
        "titleName": name,
        "volumeNumber": volume,
        "firstChapter": first,
        "lastChapter": last,
        "firstChapterSortKey": enumerate_chapters.chapter_sort_key(first),
        "lastChapterSortKey": enumerate_chapters.chapter_sort_key(last),
    }


class CandidateDigitRangeTest(unittest.TestCase):
    def test_a_range_walks_only_its_own_declared_span(self):
        titles = [_title("1", "Courts", 1, "1", "10"), _title("2", "Procedure", 1, "12", "25")]
        digits = enumerate_chapters.candidate_digit_range(titles)
        self.assertEqual(digits[0], 1)
        self.assertEqual(digits[-1], 25)
        # Chapter 11 is the published gap between these two titles.
        self.assertNotIn(11, digits)

    def test_a_lettered_endpoint_walks_by_its_own_digits_only(self):
        titles = [_title("27", "Public Contracting", 7, "284", "285C")]
        digits = enumerate_chapters.candidate_digit_range(titles)
        self.assertEqual(digits, [284, 285])

    def test_overlapping_title_ranges_do_not_duplicate_digits(self):
        titles = [_title("1", "A", 1, "1", "5"), _title("2", "B", 1, "5", "8")]
        digits = enumerate_chapters.candidate_digit_range(titles)
        self.assertEqual(digits, [1, 2, 3, 4, 5, 6, 7, 8])


class SelectTitlesTest(unittest.TestCase):
    TITLES = [_title("1", "A", 1, "1", "10"), _title("16", "B", 4, "161", "169")]

    def test_no_selection_returns_every_title(self):
        self.assertEqual(enumerate_chapters.select_titles(self.TITLES, None), self.TITLES)

    def test_a_selection_narrows_to_the_named_titles(self):
        selected = enumerate_chapters.select_titles(self.TITLES, ["16"])
        self.assertEqual([t["titleNumber"] for t in selected], ["16"])

    def test_an_unknown_title_number_is_an_error(self):
        with self.assertRaises(ValueError):
            enumerate_chapters.select_titles(self.TITLES, ["99"])


class ReadTitleRosterTest(unittest.TestCase):
    def test_a_roster_missing_a_required_field_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roster.json"
            path.write_text(json.dumps({"titles": [{"titleNumber": "1"}]}))
            with self.assertRaises(ValueError):
                enumerate_chapters.read_title_roster(path)

    def test_a_roster_with_no_titles_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roster.json"
            path.write_text(json.dumps({"titles": []}))
            with self.assertRaises(ValueError):
                enumerate_chapters.read_title_roster(path)


class _Handler(BaseHTTPRequestHandler):
    published = ()
    server_errors = ()

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        for number in self.server_errors:
            if self.path.endswith(f"ors{chapter_file_stem(number)}.html"):
                self._respond(500, b"server error")
                return
        for number in self.published:
            if self.path.endswith(f"ors{chapter_file_stem(number)}.html"):
                self._respond(200, CHAPTER_BODY.format(number=number).encode("cp1252"))
                return
        self._respond(404, b"not found")

    def _respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class EnumerationEndToEndTest(unittest.TestCase):
    # Title "9" covers chapters 90-92. Published: 90, 90A and 92 exist; 91 is
    # a bare gap; 90B and 92A are the confirmed stops after each family's
    # last real letter.
    published = ["90", "90A", "92"]

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.template = cls.base_url + "/bills_laws/ors/ors{chapter_file}.html"
        _Handler.published = tuple(cls.published)
        _Handler.server_errors = ()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        _Handler.server_errors = ()

    def _title_roster_file(self, root):
        path = root / "roster.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "rosterUrl": "https://example.test/ORS_TitlesChapters.pdf",
            "rosterSha256": "c" * 64,
            "titles": [_title("9", "Public Health", 3, "90", "92")],
        }))
        return path

    def test_enumeration_finds_every_real_chapter_and_records_every_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "roster-report.json"
            exit_code = enumerate_chapters.main([
                "--title-roster-file", str(self._title_roster_file(root)),
                "--url-template", self.template,
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["chapterCount"], 3)
            self.assertEqual(report["absenceCount"], 4)
            self.assertEqual(report["failureCount"], 0)

            by_number = {item["chapterNumber"]: item for item in report["chapters"]}
            for number in ("90", "90A", "92"):
                self.assertTrue(by_number[number]["ok"])
                self.assertEqual(len(by_number[number]["sha256"]), 64)
                self.assertEqual(by_number[number]["titleNumber"], "9")
                self.assertEqual(by_number[number]["volumeNumber"], 3)
                self.assertTrue(Path(by_number[number]["fixture"]).exists())
            for number in ("91", "91A", "90B", "92A"):
                self.assertFalse(by_number[number]["ok"])
                self.assertEqual(by_number[number]["httpStatus"], 404)

    def test_a_server_error_is_reported_as_a_failure_not_an_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _Handler.server_errors = ("91",)
            report_path = root / "roster-report.json"
            exit_code = enumerate_chapters.main([
                "--title-roster-file", str(self._title_roster_file(root)),
                "--url-template", self.template,
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertEqual(report["failureCount"], 1)
            self.assertEqual(report["failures"][0]["chapterNumber"], "91")
            self.assertEqual(report["failures"][0]["httpStatus"], 500)

    def test_a_titles_filter_narrows_the_walk(self):
        _Handler.published = tuple(self.published) + ("161",)
        self.addCleanup(setattr, _Handler, "published", tuple(self.published))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "roster.json"
            path.write_text(json.dumps({
                "titles": [
                    _title("9", "Public Health", 3, "90", "92"),
                    _title("16", "Crimes", 4, "161", "161"),
                ],
            }))
            report_path = root / "roster-report.json"
            exit_code = enumerate_chapters.main([
                "--title-roster-file", str(path),
                "--titles", "16",
                "--url-template", self.template,
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["titleRosterCount"], 1)
            numbers = {item["chapterNumber"] for item in report["chapters"] if item["ok"]}
            self.assertEqual(numbers, {"161"})

    def test_enumeration_output_feeds_the_structure_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "roster-report.json"
            enumerate_chapters.main([
                "--title-roster-file", str(self._title_roster_file(root)),
                "--url-template", self.template,
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            probe_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(report_path),
                "--report", str(probe_path),
            ])
            self.assertEqual(exit_code, 0)
            probed_numbers = {c["chapterNumber"] for c in json.loads(probe_path.read_text())["chapters"]}
            self.assertEqual(probed_numbers, {"90", "90A", "92"})


if __name__ == "__main__":
    unittest.main()
