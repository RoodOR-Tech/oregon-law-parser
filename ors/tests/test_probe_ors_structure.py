#!/usr/bin/env python3
"""Offline tests for the ORS markup structure probe."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import probe_ors_structure as probe  # noqa: E402


# A synthetic chapter shaped like the published ORS: a chapter heading, a
# subdivision heading, sections with leadlines, a bracketed source credit and a
# repeal stub. It is deliberately not a copy of any real chapter.
SYNTHETIC_CHAPTER = """
<html><head><style>.x { color: red }</style></head>
<body>
<p class="heading">Chapter 161 &mdash; General Provisions</p>
<p class="subdivision">(Definitions)</p>
<p class="section">161.005 Short title. ORS 161.005 to 161.055 shall be known
as the Oregon Criminal Code.<br>[1971 c.743 s.1]</p>
<p class="section">161.015 General definitions. As used in ORS 161.005 to
161.055, unless the context requires otherwise:<br>[1971 c.743 s.3; 1973 c.836 s.339]</p>
<p class="section">161.025 [Repealed by 1971 c.743 s.432]</p>
<script>var ignored = "161.999";</script>
</body></html>
"""


class VisibleLinesTest(unittest.TestCase):
    def test_script_and_style_content_is_removed(self):
        lines = probe.visible_lines(SYNTHETIC_CHAPTER)
        joined = "\n".join(lines)
        self.assertNotIn("161.999", joined)
        self.assertNotIn("color: red", joined)

    def test_entities_are_unescaped_and_whitespace_collapsed(self):
        lines = probe.visible_lines(SYNTHETIC_CHAPTER)
        self.assertIn("Chapter 161 — General Provisions", lines)

    def test_block_boundaries_become_line_breaks(self):
        lines = probe.visible_lines("<p>first</p><p>second</p>")
        self.assertEqual(lines, ["first", "second"])

    def test_non_breaking_spaces_do_not_survive_as_separate_tokens(self):
        lines = probe.visible_lines("<p>a&nbsp;&nbsp;b</p>")
        self.assertEqual(lines, ["a b"])


class ProbeMarkupTest(unittest.TestCase):
    def setUp(self):
        self.result = probe.probe_markup(SYNTHETIC_CHAPTER, "161")

    def test_counts_section_numbers_and_scopes_them_to_the_chapter(self):
        self.assertGreater(self.result["sectionNumberMatches"], 0)
        self.assertEqual(self.result["sectionNumbersInThisChapter"], self.result["sectionNumberMatches"])

    def test_distinguishes_section_anchors_from_wrapped_citation_lines(self):
        # Four lines open with a section number, but one of them is the wrapped
        # continuation "161.055, unless the context requires otherwise:".
        self.assertEqual(self.result["sectionNumberLineCount"], 4)
        self.assertEqual(self.result["sectionAnchorLineCount"], 3)
        self.assertEqual(self.result["ambiguousSectionLineCount"], 1)
        self.assertTrue(self.result["sampleAmbiguousSectionLines"][0].startswith("161.055,"))

    def test_section_anchors_cover_both_catchlines_and_bracketed_stubs(self):
        anchors = self.result["sampleSectionAnchorLines"]
        self.assertTrue(anchors[0].startswith("161.005 Short title."))
        self.assertTrue(anchors[2].startswith("161.025 [Repealed"))

    def test_counts_bracketed_source_credits(self):
        self.assertEqual(self.result["sourceCreditMatches"], 3)
        self.assertIn("1971 c.743", self.result["sampleSourceCredits"][0])

    def test_counts_session_citations_inside_credits(self):
        self.assertEqual(self.result["sessionCitationMatches"], 4)

    def test_counts_repeal_stubs(self):
        self.assertEqual(self.result["repealStubMatches"], 1)

    def test_reports_tag_and_class_histograms(self):
        tags = {entry["value"]: entry["count"] for entry in self.result["tagHistogram"]}
        classes = {entry["value"]: entry["count"] for entry in self.result["classHistogram"]}
        self.assertEqual(tags["p"], 5)
        self.assertEqual(classes["section"], 3)
        self.assertEqual(classes["heading"], 1)

    def test_sample_output_is_bounded(self):
        long_markup = "".join(f"<p>line {index} " + "x" * 500 + "</p>" for index in range(200))
        bounded = probe.probe_markup(long_markup, "161")
        self.assertEqual(len(bounded["sampleLines"]), probe.MAX_SAMPLE_LINES)
        self.assertLessEqual(
            max(len(line) for line in bounded["sampleLines"]),
            probe.MAX_SAMPLE_LINE_CHARS,
        )

    def test_chapter_scoping_is_skipped_when_no_chapter_is_given(self):
        self.assertIsNone(probe.probe_markup(SYNTHETIC_CHAPTER)["sectionNumbersInThisChapter"])


class ProbeCliTest(unittest.TestCase):
    def _acquisition_report(self, root, chapters):
        path = root / "acquisition.json"
        path.write_text(json.dumps({"schemaVersion": 1, "chapters": chapters}))
        return path

    def test_probes_every_acquired_html_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "ors161.html"
            fixture.write_text(SYNTHETIC_CHAPTER)
            acquisition = self._acquisition_report(root, [{
                "chapterNumber": "161",
                "ok": True,
                "sourceFormat": "html",
                "fixture": str(fixture),
                "sourceUrl": "https://example.test/ors161.html",
                "sha256": "a" * 64,
                "bytes": len(SYNTHETIC_CHAPTER),
            }])
            report_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(acquisition),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["probedChapterCount"], 1)
            self.assertEqual(report["chapters"][0]["chapterNumber"], "161")
            self.assertEqual(report["chapters"][0]["sha256"], "a" * 64)

    def test_failed_acquisitions_are_not_probed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquisition = self._acquisition_report(root, [{
                "chapterNumber": "161",
                "ok": False,
                "error": "HTTP 404",
            }])
            report_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(acquisition),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["probedChapterCount"], 0)
            self.assertFalse(report["valid"])

    def test_a_missing_fixture_is_reported_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquisition = self._acquisition_report(root, [{
                "chapterNumber": "161",
                "ok": True,
                "sourceFormat": "html",
                "fixture": str(root / "absent.html"),
            }])
            report_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(acquisition),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["unreadableChapterCount"], 1)
            self.assertEqual(report["unreadable"][0]["error"], "fixture missing")

    def test_a_pdf_chapter_is_recorded_as_unprobed_rather_than_probed_wrongly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "ors161.pdf"
            fixture.write_bytes(b"%PDF-1.7\n")
            acquisition = self._acquisition_report(root, [{
                "chapterNumber": "161",
                "ok": True,
                "sourceFormat": "pdf",
                "fixture": str(fixture),
            }])
            report_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(acquisition),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertIn("unsupported probe format", report["unreadable"][0]["error"])


if __name__ == "__main__":
    unittest.main()
