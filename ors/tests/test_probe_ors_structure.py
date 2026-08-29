#!/usr/bin/env python3
"""Offline tests for the ORS markup structure probe."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import probe_ors_structure as probe  # noqa: E402
from ors_text import decode_markup, declared_charset  # noqa: E402


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


class StructuralDefectTest(unittest.TestCase):
    """A 200 response that parses as HTML is not thereby a chapter."""

    OUTAGE_PAGE = (
        "<html><head><title>Site Maintenance</title></head><body>"
        "<p>This service is temporarily unavailable. Please try again later.</p>"
        "</body></html>"
    )

    def test_an_outage_page_is_rejected_rather_than_probed(self):
        result = probe.probe_markup(self.OUTAGE_PAGE, "161")
        defect = probe.structural_defect(result, "161")
        self.assertIsNotNone(defect)
        self.assertIn("no section numbers in chapter 161", defect)

    def test_a_document_for_a_different_chapter_is_rejected(self):
        markup = "<html><body><p>90.100 Definitions. Text.</p></body></html>"
        result = probe.probe_markup(markup, "161")
        defect = probe.structural_defect(result, "161")
        self.assertIsNotNone(defect)
        self.assertIn("chapter 161", defect)

    def test_an_empty_document_is_rejected(self):
        result = probe.probe_markup("<html><body></body></html>", "161")
        self.assertEqual(probe.structural_defect(result, "161"), "document has no visible text")

    def test_a_real_chapter_document_has_no_defect(self):
        result = probe.probe_markup(SYNTHETIC_CHAPTER, "161")
        self.assertIsNone(probe.structural_defect(result, "161"))

    def test_page_title_is_recovered_for_the_unreadable_record(self):
        self.assertEqual(probe.page_title(self.OUTAGE_PAGE), "Site Maintenance")
        self.assertIsNone(probe.page_title("<html><body>no title</body></html>"))


class WordExportFixtureTest(unittest.TestCase):
    """Measured against a fixture modelled on the published chapter documents.

    The real sources are Microsoft Word HTML exports in Windows-1252 with a
    table of contents ahead of the body, non-breaking spaces separating a
    section number from its catchline, and section symbols in the credits.
    """

    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "word_export_chapter.html"

    @classmethod
    def setUpClass(cls):
        data = cls.FIXTURE.read_bytes()
        cls.markup, cls.encoding = decode_markup(data, declared_charset(data))
        cls.result = probe.probe_markup(cls.markup, "161")

    def test_the_document_is_decoded_as_the_windows_encoding_it_declares(self):
        self.assertEqual(self.encoding, "windows-1252")
        self.assertIn("§", self.markup)
        self.assertIn("—", self.markup)
        self.assertNotIn("\ufffd", self.markup)

    def test_section_symbols_survive_into_the_parsed_credits(self):
        self.assertIn("[1971 c.743 §1]", self.result["sampleSourceCredits"])
        self.assertEqual(self.result["sourceCreditMatches"], 3)

    def test_bold_runs_identify_exactly_the_body_sections(self):
        # Bold is the separator between the body and the table of contents:
        # the chapter has four body sections and the count matches.
        self.assertEqual(self.result["boldSectionAnchorCount"], 4)
        self.assertEqual(self.result["distinctBoldSectionAnchors"], 4)
        self.assertEqual(
            self.result["sampleBoldSectionAnchors"][:2],
            ["161.005 Short title.", "161.015 General definitions."],
        )

    def test_line_anchoring_overcounts_because_the_contents_repeats_the_numbers(self):
        # Four body sections plus four contents entries. This is why line
        # position alone cannot segment a chapter.
        self.assertEqual(self.result["sectionAnchorLineCount"], 8)
        self.assertEqual(self.result["boldSectionAnchorCount"], 4)

    def test_non_breaking_space_separators_do_not_defeat_the_anchor(self):
        # The published layout separates number from catchline with
        # non-breaking spaces, which are not ordinary whitespace.
        self.assertIn("\u00a0", self.FIXTURE.read_bytes().decode("cp1252"))
        self.assertTrue(probe.is_section_anchor("161.005\u00a0Short title."))

    def test_wrapped_citation_lines_are_not_treated_as_section_starts(self):
        ambiguous = self.result["sampleAmbiguousSectionLines"]
        self.assertTrue(any(line.startswith("161.055 (2)") for line in ambiguous))
        self.assertFalse(probe.is_section_anchor("161.055 (2) does not apply"))

    def test_a_wrapped_credit_bracket_is_not_mistaken_for_a_repeal_stub(self):
        self.assertFalse(probe.is_section_anchor("279B.405 [2003 c.794 §2;"))
        self.assertTrue(probe.is_section_anchor("279B.405 [Repealed by 2003 c.794 §2]"))

    def test_the_probe_records_the_encoding_it_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acquisition = root / "acquisition.json"
            acquisition.write_text(json.dumps({"schemaVersion": 1, "chapters": [{
                "chapterNumber": "161",
                "ok": True,
                "sourceFormat": "html",
                "fixture": str(self.FIXTURE),
            }]}))
            report_path = root / "probe.json"
            self.assertEqual(probe.main([
                "--acquisition-report", str(acquisition),
                "--report", str(report_path),
            ]), 0)
            chapter = json.loads(report_path.read_text())["chapters"][0]
            self.assertEqual(chapter["sourceEncoding"], "windows-1252")
            self.assertEqual(chapter["declaredCharset"], "windows-1252")


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

    def test_an_outage_page_fails_the_probe_gate_instead_of_becoming_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "ors161.html"
            fixture.write_text(StructuralDefectTest.OUTAGE_PAGE)
            acquisition = self._acquisition_report(root, [{
                "chapterNumber": "161",
                "ok": True,
                "sourceFormat": "html",
                "fixture": str(fixture),
                "sourceUrl": "https://example.test/ors161.html",
                "sha256": "b" * 64,
                "bytes": len(StructuralDefectTest.OUTAGE_PAGE),
            }])
            report_path = root / "probe.json"
            exit_code = probe.main([
                "--acquisition-report", str(acquisition),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertEqual(report["probedChapterCount"], 0)
            self.assertEqual(report["unreadableChapterCount"], 1)
            unreadable = report["unreadable"][0]
            self.assertEqual(unreadable["pageTitle"], "Site Maintenance")
            self.assertIn("no section numbers in chapter 161", unreadable["error"])

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
