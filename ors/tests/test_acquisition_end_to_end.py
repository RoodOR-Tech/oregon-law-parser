#!/usr/bin/env python3
"""End-to-end acquisition tests against a loopback HTTP server.

These exercise the real download path — concurrent fetching, digest pinning,
404 handling and the structured failure report — without reaching the Oregon
Legislature site, so they run anywhere the unit tests run.
"""
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import acquire_ors_chapters as acquire  # noqa: E402
import probe_ors_structure as probe  # noqa: E402
from ors_chapters import chapter_file_stem  # noqa: E402

CHAPTER_BODY = (
    "<html><body><p>Chapter {number}</p>"
    "<p><b>{number}.005 Short title.</b> Text of the section. [1971 c.743 &sect;1]</p>"
    "</body></html>"
)


class _Handler(BaseHTTPRequestHandler):
    published = ()

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
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


class AcquisitionEndToEndTest(unittest.TestCase):
    rostered = ["1", "161", "279A"]
    # Chapter 279A is on the roster but not served, standing in for a roster
    # entry whose document is missing from the published site.
    served = ["1", "161"]

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.template = cls.base_url + "/bills_laws/ors/ors{chapter_file}.html"
        _Handler.published = tuple(cls.served)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _roster_file(self, root):
        path = root / "roster.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "rosterUrl": "https://example.test/ORS_TitlesChapters.pdf",
            "rosterSha256": "c" * 64,
            "editionYear": 2025,
            "editionId": "2025",
            "chapters": [
                {
                    "chapterNumber": number,
                    "chapterName": f"Chapter {number}",
                    "titleNumber": "1",
                    "sourceUrl": self.template.format(chapter_file=chapter_file_stem(number)),
                }
                for number in self.rostered
            ],
        }))
        return path

    def test_roster_backed_acquisition_pins_digests_and_carries_roster_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "acquisition.json"
            exit_code = acquire.main([
                "--roster-file", str(self._roster_file(root)),
                "--chapters", "1,161",
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertTrue(report["rosterVerified"])
            self.assertEqual(report["chapterUrlSource"], "roster")
            self.assertEqual(report["editionId"], "2025")
            self.assertEqual(report["rosterChapterCount"], 3)
            self.assertEqual(report["acquiredChapterCount"], 2)
            for chapter in report["chapters"]:
                self.assertEqual(len(chapter["sha256"]), 64)
                self.assertEqual(chapter["sourceFormat"], "html")
                # Roster metadata travels with the acquired document.
                self.assertEqual(chapter["titleNumber"], "1")
                self.assertTrue(chapter["chapterName"])
                fixture = Path(chapter["fixture"])
                self.assertEqual(fixture.stat().st_size, chapter["bytes"])

    def test_a_rostered_but_unpublished_chapter_is_a_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "acquisition.json"
            exit_code = acquire.main([
                "--roster-file", str(self._roster_file(root)),
                "--chapters", "1,279A",
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            failure = report["failures"][0]
            self.assertEqual(failure["chapterNumber"], "279A")
            self.assertEqual(failure["httpStatus"], 404)
            # A 404 is an answer, so it must not consume the retry budget.
            self.assertEqual(failure["attempts"], 1)

    def test_requesting_a_chapter_absent_from_the_roster_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "acquisition.json"
            exit_code = acquire.main([
                "--roster-file", str(self._roster_file(root)),
                "--chapters", "999",
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertIn("not present in the published roster", report["error"])

    def test_without_roster_constructs_urls_and_declares_itself_unverified(self):
        # Naming a chapter is not the same as synthesizing a roster, so the
        # run is usable but must declare that its roster was never verified.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "acquisition.json"
            exit_code = acquire.main([
                "--without-roster",
                "--chapters", "1,161",
                "--url-template", self.template,
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertFalse(report["rosterVerified"])
            self.assertEqual(report["chapterUrlSource"], "constructed")
            self.assertIsNone(report["rosterChapterCount"])
            self.assertEqual(report["acquiredChapterCount"], 2)

    def test_a_roster_source_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit):
                acquire.main([
                    "--chapters", "1",
                    "--output-dir", str(root / "sources"),
                    "--report", str(root / "acquisition.json"),
                ])

    def test_without_roster_requires_an_explicit_chapter_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(SystemExit):
                acquire.main([
                    "--without-roster",
                    "--output-dir", str(root / "sources"),
                    "--report", str(root / "acquisition.json"),
                ])

    def test_acquisition_output_feeds_the_structure_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquisition_path = root / "acquisition.json"
            acquire.main([
                "--roster-file", str(self._roster_file(root)),
                "--chapters", "161",
                "--output-dir", str(root / "sources"),
                "--report", str(acquisition_path),
                "--retries", "1",
            ])
            probe_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(acquisition_path),
                "--report", str(probe_path),
            ])
            self.assertEqual(exit_code, 0)
            chapter = json.loads(probe_path.read_text())["chapters"][0]
            self.assertEqual(chapter["chapterNumber"], "161")
            self.assertEqual(chapter["boldSectionAnchorCount"], 1)
            self.assertEqual(chapter["sourceCreditMatches"], 1)


class SampleFileTest(unittest.TestCase):
    """The committed development sample must stay usable by the pipeline."""

    SAMPLE = Path(__file__).resolve().parents[1] / "sample" / "chapters.json"

    def test_sample_manifest_parses_and_every_number_is_well_formed(self):
        numbers = acquire.read_chapter_selection_file(self.SAMPLE)
        self.assertGreaterEqual(len(numbers), 5)
        for number in numbers:
            self.assertIsNotNone(acquire.parse_chapter_number(number))

    def test_sample_covers_both_numeric_and_lettered_chapters(self):
        numbers = acquire.read_chapter_selection_file(self.SAMPLE)
        self.assertTrue(any(number[-1].isdigit() for number in numbers))
        self.assertTrue(any(number[-1].isalpha() for number in numbers))

    def test_sample_entries_are_unique_and_each_records_a_rationale(self):
        document = json.loads(self.SAMPLE.read_text())
        numbers = [entry["chapterNumber"] for entry in document["chapters"]]
        self.assertEqual(len(numbers), len(set(numbers)))
        for entry in document["chapters"]:
            self.assertTrue(entry["rationale"].strip())

    def test_an_empty_selection_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chapters.json"
            path.write_text(json.dumps({"chapters": []}))
            with self.assertRaises(ValueError):
                acquire.read_chapter_selection_file(path)

    def test_a_malformed_selection_entry_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chapters.json"
            path.write_text(json.dumps({"chapters": [{"rationale": "no number"}]}))
            with self.assertRaises(ValueError):
                acquire.read_chapter_selection_file(path)


if __name__ == "__main__":
    unittest.main()
