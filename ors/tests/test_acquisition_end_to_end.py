#!/usr/bin/env python3
"""End-to-end acquisition test against a loopback HTTP server.

This exercises the real download path — discovery, concurrent fetching, digest
pinning, 404 handling and the structured failure report — without reaching the
Oregon Legislature site, so it runs anywhere the unit tests run.
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

CHAPTER_BODY = (
    "<html><body><p>Chapter {number}</p>"
    "<p>{number}.005 Short title. Text of the section.<br>[1971 c.743 s.1]</p>"
    "</body></html>"
)


def index_page(base_url, chapters):
    links = "".join(
        f'<a href="{base_url}/bills_laws/ors/ors{acquire.chapter_file_stem(number)}.html">{number}</a>'
        for number in chapters
    )
    return f"<html><body><h1>2025 Edition</h1>{links}</body></html>"


class _Handler(BaseHTTPRequestHandler):
    index_html = ""
    published = ()

    def do_GET(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        if self.path.endswith("ors.aspx"):
            self._respond(200, self.index_html.encode())
            return
        for number in self.published:
            if self.path.endswith(f"ors{acquire.chapter_file_stem(number)}.html"):
                self._respond(200, CHAPTER_BODY.format(number=number).encode())
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
    listed = ["1", "161", "279A"]
    # Chapter 279A is listed by the index but not served, standing in for a
    # roster entry whose document is missing from the published site.
    served = ["1", "161"]

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        _Handler.index_html = index_page(cls.base_url, cls.listed)
        _Handler.published = tuple(cls.served)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    @property
    def index_url(self):
        return f"{self.base_url}/bills_laws/pages/ors.aspx"

    def test_index_only_discovers_the_served_roster(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "index.json"
            exit_code = acquire.main([
                "--index-only",
                "--index-url", self.index_url,
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertEqual(
                [item["chapterNumber"] for item in report["chapters"]], self.listed
            )
            self.assertEqual(report["indexHttpStatus"], 200)
            self.assertEqual(report["indexSource"], "network")

    def test_acquisition_pins_digests_and_writes_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "acquisition.json"
            exit_code = acquire.main([
                "--index-url", self.index_url,
                "--chapters", "1,161",
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["acquiredChapterCount"], 2)
            for chapter in report["chapters"]:
                self.assertTrue(chapter["ok"])
                self.assertEqual(len(chapter["sha256"]), 64)
                self.assertEqual(chapter["sourceFormat"], "html")
                fixture = Path(chapter["fixture"])
                self.assertTrue(fixture.exists())
                self.assertEqual(fixture.stat().st_size, chapter["bytes"])

    def test_a_listed_but_unpublished_chapter_is_a_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "acquisition.json"
            exit_code = acquire.main([
                "--index-url", self.index_url,
                "--chapters", "1,279A",
                "--output-dir", str(root / "sources"),
                "--report", str(report_path),
                "--retries", "1",
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertEqual(report["acquiredChapterCount"], 1)
            self.assertEqual(len(report["failures"]), 1)
            failure = report["failures"][0]
            self.assertEqual(failure["chapterNumber"], "279A")
            self.assertEqual(failure["httpStatus"], 404)
            # A 404 is an answer, so it must not consume the retry budget.
            self.assertEqual(failure["attempts"], 1)

    def test_acquisition_output_feeds_the_structure_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquisition_path = root / "acquisition.json"
            acquire.main([
                "--index-url", self.index_url,
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
            report = json.loads(probe_path.read_text())
            chapter = report["chapters"][0]
            self.assertEqual(chapter["chapterNumber"], "161")
            self.assertEqual(chapter["sectionAnchorLineCount"], 1)
            self.assertEqual(chapter["sourceCreditMatches"], 1)


if __name__ == "__main__":
    unittest.main()
