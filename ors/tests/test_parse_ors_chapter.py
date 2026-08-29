#!/usr/bin/env python3
"""Tests for parsing ORS chapter documents into relational rows.

The fixture reproduces the layout measured from the published exports: a
Windows-1252 Word HTML export whose table of contents repeats every section
number unbolded, body headings in bold, non-breaking-space separators,
centred subdivision headings, and bracketed disposition stubs.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import parse_ors_chapter as parser  # noqa: E402
from ors_text import decode_markup, declared_charset  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "word_export_chapter.html"
# Chapter 1 opens its title, so its document carries the title's front matter
# ahead of its own heading and edition banner.
FRONT_MATTER_FIXTURE = FIXTURES / "title_front_matter_chapter.html"


def parsed(path, chapter_number):
    data = path.read_bytes()
    markup, _ = decode_markup(data, declared_charset(data))
    return parser.parse_chapter(markup, chapter_number)


def parsed_fixture():
    return parsed(FIXTURE, "161")


class ChapterIdentityTest(unittest.TestCase):
    def setUp(self):
        self.result = parsed_fixture()

    def test_the_chapter_names_itself_in_its_own_heading(self):
        self.assertEqual(self.result["printedChapterNumber"], "161")
        self.assertEqual(self.result["chapterName"], "General Provisions")

    def test_the_edition_comes_from_the_chapter_document(self):
        # The table of titles carries no edition banner; the chapter documents
        # print one, so edition identity is established here.
        self.assertEqual(self.result["editionYear"], 2025)

    def test_a_document_without_an_edition_banner_reports_none(self):
        self.assertIsNone(parser.parse_chapter("<p>161.005 Short title.</p>", "161")["editionYear"])

    def test_a_bare_year_without_the_word_edition_is_not_an_edition(self):
        markup = "<p>2025</p><p>c.88</p><p><b>161.005 Short title.</b> Text.</p>"
        self.assertIsNone(parser.parse_chapter(markup, "161")["editionYear"])


class TitleFrontMatterTest(unittest.TestCase):
    """A chapter that opens a title carries that title's front matter first.

    Chapter 1's document begins "TITLE / 1 / COURTS / OF RECORD; COURT
    OFFICERS; JURIES" and lists the title's chapters before reaching its own
    heading and edition banner. A fixed head window missed both.
    """

    def setUp(self):
        self.result = parsed(FRONT_MATTER_FIXTURE, "1")

    def test_the_heading_is_found_past_the_front_matter(self):
        self.assertEqual(self.result["printedChapterNumber"], "1")
        self.assertEqual(
            self.result["chapterName"], "Courts and Judicial Officers Generally"
        )

    def test_the_edition_banner_is_found_past_the_front_matter(self):
        self.assertEqual(self.result["editionYear"], 2025)

    def test_the_front_matter_chapter_list_does_not_become_sections(self):
        # "Chapter 1. Courts and", "2. Supreme", "3. Circuit" and the rest are
        # a list of the title's chapters, not sections of this one.
        self.assertEqual(
            [item["sectionNumber"] for item in self.result["sections"]],
            ["1.001", "1.002"],
        )

    def test_a_heading_for_another_chapter_is_never_accepted(self):
        # Searching the whole document must not pick up a different chapter's
        # heading just because it appears first.
        text = "<p>90 – Residential Landlord and Tenant</p><p>161 – General Provisions</p>"
        lines = list(parser.line_spans(parser.normalize_chapter_text(text)[0]))
        self.assertEqual(parser.parse_chapter_heading(lines, "161")[0], "161")


class ForeignAnchorTest(unittest.TestCase):
    def test_a_bolded_citation_to_another_chapter_is_not_a_section(self):
        markup = (
            "<p><b>161.005 Short title.</b> See <b>90.100 Definitions.</b> too.</p>"
            "<p>2025</p><p>EDITION</p>"
        )
        result = parser.parse_chapter(markup, "161")
        self.assertEqual([item["sectionNumber"] for item in result["sections"]], ["161.005"])
        self.assertEqual(result["foreignAnchors"], ["90.100"])
        # It is recorded, not treated as this chapter's defect.
        self.assertEqual(result["problems"], [])


class ChapterHeadingLayoutTest(unittest.TestCase):
    def test_the_chapter_prefix_may_share_the_heading_line(self):
        # The heading prints "Chapter" above the number and name, separated by
        # a source newline. The parser rejoins those into one logical line, so
        # the heading arrives as "Chapter 192 - Records; ...".
        markup = (
            "<p><span>Chapter\n192 &#8211; Records; Public Reports and Meetings</span></p>"
            "<p>2025\nEDITION</p><p><b>192.001 Policy.</b> Text.</p>"
        )
        result = parser.parse_chapter(markup, "192")
        self.assertEqual(result["printedChapterNumber"], "192")
        self.assertEqual(result["chapterName"], "Records; Public Reports and Meetings")
        self.assertIsNone(result["headingDiagnostics"])

    def test_a_missing_heading_explains_itself(self):
        # chapter_name is a schema column, so a chapter without one is a gap
        # that has to be visible rather than a nullable convenience.
        markup = "<p>2025 EDITION</p><p><b>192.001 Policy.</b> Text.</p>"
        result = parser.parse_chapter(markup, "192")
        self.assertIsNone(result["chapterName"])
        diagnostics = result["headingDiagnostics"]
        self.assertIsNotNone(diagnostics)
        self.assertIn("2025 EDITION", diagnostics["sampleLines"])

    def test_a_chapter_without_a_name_fails_the_run(self):
        record = {
            "chapterNumber": "192",
            "chapterSortKey": "000192 ",
            "sha256": "a" * 64,
            "parsed": parser.parse_chapter(
                "<p>2025 EDITION</p><p><b>192.001 Policy.</b> Text.</p>", "192"
            ),
        }
        rows = parser.build_rows([record])
        self.assertEqual(rows["chapters"][0]["chapterName"], None)
        self.assertEqual(
            [c["chapterNumber"] for c in rows["chapters"] if not c["chapterName"]], ["192"]
        )


class EditionBannerTest(unittest.TestCase):
    def test_a_source_newline_inside_the_banner_yields_one_logical_line(self):
        # The published banner puts a literal newline between the year and the
        # word, with no tag between them:
        #
        #     <p ...><b><span ...>2025
        #     EDITION<o:p></o:p></span></b></p>
        #
        # The probe treats a source newline as a line break, which is why it
        # reported "2025" and "EDITION" as adjacent lines. This parser rejoins
        # wrapped text into logical lines instead, so the same banner arrives
        # as one line. Reading only the two-line form missed it in every
        # chapter of the sample.
        markup = (
            "<p class=MsoNormal align=center><b><span style='font-size:14.0pt'>2025\n"
            "EDITION<o:p></o:p></span></b></p>"
            "<p><b><span>161.005&nbsp;Short title.</span></b><span> Text.</span></p>"
        )
        text, _ = parser.normalize_chapter_text(markup)
        self.assertIn("2025 EDITION", [line for line, _, _ in parser.line_spans(text)])
        self.assertEqual(parser.parse_chapter(markup, "161")["editionYear"], 2025)

    def test_both_printed_banner_layouts_are_read(self):
        two_line = "<p>2025</p><p>EDITION</p><p><b>161.005 Short title.</b> Text.</p>"
        one_line = "<p>2025 EDITION</p><p><b>161.005 Short title.</b> Text.</p>"
        self.assertEqual(parser.parse_chapter(two_line, "161")["editionYear"], 2025)
        self.assertEqual(parser.parse_chapter(one_line, "161")["editionYear"], 2025)

    def test_a_year_in_running_text_is_not_a_banner(self):
        markup = (
            "<p>ORS sections in this chapter were amended during its 2026 regular"
            " session.</p><p><b>161.005 Short title.</b> Text.</p>"
        )
        self.assertIsNone(parser.parse_chapter(markup, "161")["editionYear"])

    def test_a_missing_banner_explains_itself(self):
        # A missing banner stops every row for the chapter, so the reason has
        # to be legible from the report rather than inferred from an absence.
        markup = (
            "<p>Oregon Revised Statutes</p><p>Chapter</p>"
            "<p>161 &#8212; General Provisions</p>"
            "<p><b>161.005 Short title.</b> Text.</p>"
        )
        result = parser.parse_chapter(markup, "161")
        diagnostics = result["editionDiagnostics"]
        self.assertIsNotNone(diagnostics)
        self.assertGreater(diagnostics["lineCount"], 0)
        self.assertIn("Oregon Revised Statutes", diagnostics["sampleLines"])
        self.assertEqual(diagnostics["editionMentions"], [])

    def test_a_found_banner_leaves_no_diagnostics(self):
        markup = "<p>2025</p><p>EDITION</p><p><b>161.005 Short title.</b> Text.</p>"
        self.assertIsNone(parser.parse_chapter(markup, "161")["editionDiagnostics"])

    def test_an_edition_mention_is_reported_with_its_neighbours(self):
        markup = (
            "<p>Prior line</p><p>2025 EDITION OF SOMETHING ELSE ENTIRELY HERE</p>"
            "<p>Next line</p><p><b>161.005 Short title.</b> Text.</p>"
        )
        result = parser.parse_chapter(markup, "161")
        # This banner form does match, so no diagnostics; the mention capture
        # is exercised where the word appears without a usable year.
        markup = (
            "<p>Prior line</p><p>SPECIAL EDITION</p><p>Next line</p>"
            "<p><b>161.005 Short title.</b> Text.</p>"
        )
        diagnostics = parser.parse_chapter(markup, "161")["editionDiagnostics"]
        self.assertEqual(diagnostics["editionMentions"][0]["line"], "SPECIAL EDITION")
        self.assertEqual(diagnostics["editionMentions"][0]["previous"], "Prior line")
        self.assertEqual(diagnostics["editionMentions"][0]["next"], "Next line")


class SegmentationTest(unittest.TestCase):
    def setUp(self):
        self.result = parsed_fixture()

    def test_sections_are_anchored_on_bold_runs_not_line_position(self):
        # The contents list repeats all four numbers unbolded. Anchoring on
        # line position would find eight sections; bold finds the four real ones.
        self.assertEqual(len(self.result["sections"]), 4)
        self.assertEqual(
            [item["sectionNumber"] for item in self.result["sections"]],
            ["161.005", "161.015", "161.025", "161.035"],
        )

    def test_adjacent_bold_headings_are_separate_spans(self):
        # Two bold headings separated only by a block boundary must not merge:
        # when they did, the second section vanished into the first's credit.
        self.assertEqual(self.result["boldRunCount"], 4)

    def test_a_wrapped_subsection_citation_is_not_a_section(self):
        numbers = [item["sectionNumber"] for item in self.result["sections"]]
        self.assertNotIn("161.055", numbers)

    def test_every_section_reports_a_non_empty_span(self):
        for section in self.result["sections"]:
            self.assertLess(section["charOffsetStart"], section["charOffsetEnd"])

    def test_section_spans_do_not_overlap(self):
        spans = [(s["charOffsetStart"], s["charOffsetEnd"]) for s in self.result["sections"]]
        for earlier, later in zip(spans, spans[1:]):
            self.assertLessEqual(earlier[1], later[0])


class SubdivisionTest(unittest.TestCase):
    def setUp(self):
        self.result = parsed_fixture()

    def test_only_headings_that_divide_sections_are_recorded(self):
        # The contents region repeats the same heading and the edition banner
        # looks like one; neither has a section beneath it.
        self.assertEqual(
            [item["headingText"] for item in self.result["subdivisions"]],
            ["GENERAL PROVISIONS", "(Definitions)"],
        )

    def test_sections_are_attributed_to_the_heading_above_them(self):
        by_number = {item["sectionNumber"]: item for item in self.result["sections"]}
        self.assertEqual(by_number["161.005"]["subdivisionHeading"], "GENERAL PROVISIONS")
        self.assertEqual(by_number["161.015"]["subdivisionHeading"], "(Definitions)")

    def test_the_edition_banner_is_not_a_subdivision(self):
        headings = [item["headingText"] for item in self.result["subdivisions"]]
        self.assertNotIn("EDITION", headings)


class SectionContentTest(unittest.TestCase):
    def setUp(self):
        self.by_number = {
            item["sectionNumber"]: item for item in parsed_fixture()["sections"]
        }

    def test_catchline_is_separated_from_the_body(self):
        section = self.by_number["161.005"]
        self.assertEqual(section["catchline"], "Short title.")
        self.assertTrue(section["bodyText"].startswith("ORS 161.005 to 161.055 shall be"))

    def test_a_trailing_source_credit_is_kept_out_of_the_body(self):
        section = self.by_number["161.005"]
        self.assertEqual(section["sourceCreditRaw"], "[1971 c.743 §1]")
        self.assertNotIn("[1971", section["bodyText"])

    def test_a_multi_session_credit_is_captured_whole(self):
        self.assertEqual(
            self.by_number["161.015"]["sourceCreditRaw"],
            "[1971 c.743 §3; 1973 c.836 §339; 2025 c.161 §4]",
        )

    def test_a_subdivision_heading_does_not_swallow_the_section_credit(self):
        # 161.005 is followed by the "(Definitions)" heading before the next
        # section. The heading ends the body rather than trailing it.
        self.assertNotIn("Definitions", self.by_number["161.005"]["bodyText"])
        self.assertIsNotNone(self.by_number["161.005"]["sourceCreditRaw"])


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.by_number = {
            item["sectionNumber"]: item for item in parsed_fixture()["sections"]
        }

    def test_an_operative_section_is_operative(self):
        self.assertEqual(self.by_number["161.005"]["status"], "operative")

    def test_the_final_disposition_wins_over_an_earlier_amendment(self):
        # "[Amended by 1961 c.160 §4; repealed by 1971 c.743 §432]" is a
        # repeal, not an amendment.
        section = self.by_number["161.025"]
        self.assertEqual(section["status"], "repealed")
        self.assertIsNone(section["bodyText"])

    def test_a_renumbering_records_its_destination(self):
        section = self.by_number["161.035"]
        self.assertEqual(section["status"], "renumbered")
        self.assertEqual(section["renumberedTo"], "161.045")

    def test_classify_stub_covers_every_disposition(self):
        self.assertEqual(parser.classify_stub("[Repealed by 1971 c.743 §432]"), ("repealed", None))
        self.assertEqual(parser.classify_stub("[Reserved for expansion]"), ("reserved", None))
        self.assertEqual(parser.classify_stub("[Formerly 646.185]"), ("note_only", None))
        self.assertEqual(
            parser.classify_stub("[Renumbered 161.045]"), ("renumbered", "161.045")
        )


class SectionSortKeyTest(unittest.TestCase):
    def test_sections_order_the_way_the_statute_book_does(self):
        numbers = ["161.100", "161.005", "279A.050", "161.067", "90.100"]
        self.assertEqual(
            sorted(numbers, key=parser.section_sort_key),
            ["90.100", "161.005", "161.067", "161.100", "279A.050"],
        )

    def test_the_fractional_part_is_not_treated_as_a_number(self):
        # 161.100 must not sort before 161.067 as 100 > 67 would suggest when
        # the fraction is read as an integer.
        self.assertLess(parser.section_sort_key("161.067"), parser.section_sort_key("161.100"))


class IntegrityTest(unittest.TestCase):
    def _rows(self):
        record = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "titleNumber": "16",
            "volumeNumber": 4,
            "sourceUrl": "https://example.test/ors161.html",
            "sha256": "a" * 64,
            "bytes": 1234,
            "sourceEncoding": "windows-1252",
            "parsed": parsed_fixture(),
        }
        return parser.build_rows([record])

    def test_a_clean_parse_violates_nothing(self):
        self.assertEqual(parser.check_referential_integrity(self._rows()), [])

    def test_a_chapter_without_a_pinned_digest_is_a_violation(self):
        rows = self._rows()
        rows["chapters"][0]["sourceSha256"] = None
        self.assertTrue(
            any("pinned digest" in item for item in parser.check_referential_integrity(rows))
        )

    def test_a_section_filed_under_the_wrong_chapter_is_a_violation(self):
        rows = self._rows()
        rows["sections"][0]["sectionNumber"] = "90.100"
        self.assertTrue(
            any("filed under chapter" in item for item in parser.check_referential_integrity(rows))
        )

    def test_an_unknown_status_is_a_violation(self):
        rows = self._rows()
        rows["sections"][0]["status"] = "probably-fine"
        self.assertTrue(
            any("unknown status" in item for item in parser.check_referential_integrity(rows))
        )

    def test_a_dangling_subdivision_reference_is_a_violation(self):
        rows = self._rows()
        rows["sections"][0]["subdivisionId"] = "2025-161-sd9999"
        self.assertTrue(
            any("dangling subdivision" in item for item in parser.check_referential_integrity(rows))
        )

    def test_a_chapter_with_no_edition_emits_no_rows(self):
        record = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "sha256": "a" * 64,
            "parsed": parser.parse_chapter("<p><b>161.005 Short title.</b> Text.</p>", "161"),
        }
        rows = parser.build_rows([record])
        self.assertEqual(rows["chapters"], [])
        self.assertEqual(rows["sections"], [])
        self.assertTrue(any("no ORS edition year" in item for item in rows["problems"]))


class ParseCliTest(unittest.TestCase):
    def _acquisition(self, root, **overrides):
        chapter = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "ok": True,
            "sourceFormat": "html",
            "fixture": str(FIXTURE),
            "sourceUrl": "https://example.test/ors161.html",
            "sha256": "a" * 64,
            "bytes": 1234,
            "titleNumber": "16",
            "volumeNumber": 4,
        }
        chapter.update(overrides)
        path = root / "acquisition.json"
        path.write_text(json.dumps({"schemaVersion": 1, "chapters": [chapter]}))
        return path

    def test_a_chapter_becomes_edition_chapter_subdivision_and_section_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "parse.json"
            rows_path = root / "rows.json"
            exit_code = parser.main([
                "--acquisition-report", str(self._acquisition(root)),
                "--report", str(report_path),
                "--rows", str(rows_path),
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["editionCount"], 1)
            self.assertEqual(report["sectionRowCount"], 4)
            self.assertEqual(report["subdivisionRowCount"], 2)
            self.assertEqual(report["integrityViolations"], [])
            self.assertEqual(
                report["statusCounts"], {"operative": 2, "renumbered": 1, "repealed": 1}
            )

            rows = json.loads(rows_path.read_text())
            self.assertEqual(rows["editions"][0]["editionId"], "2025")
            self.assertEqual(rows["chapters"][0]["chapterId"], "2025-161")
            self.assertEqual(rows["chapters"][0]["sourceSha256"], "a" * 64)
            self.assertEqual(rows["sections"][0]["sectionId"], "2025-161.005")
            # Roster identity travels through to the emitted chapter row.
            self.assertEqual(rows["chapters"][0]["titleNumber"], "16")
            self.assertEqual(rows["chapters"][0]["volumeNumber"], 4)

    def test_a_missing_fixture_is_reported_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "parse.json"
            exit_code = parser.main([
                "--acquisition-report",
                str(self._acquisition(root, fixture=str(root / "absent.html"))),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertEqual(report["unreadable"][0]["error"], "fixture missing")

    def test_a_failed_acquisition_is_not_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "parse.json"
            exit_code = parser.main([
                "--acquisition-report", str(self._acquisition(root, ok=False)),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            self.assertEqual(json.loads(report_path.read_text())["parsedChapterCount"], 0)


if __name__ == "__main__":
    unittest.main()
