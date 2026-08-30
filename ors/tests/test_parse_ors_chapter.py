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


class CreditFollowedByANoteTest(unittest.TestCase):
    """A trailing "Note:" block must not hide the section's own credit.

    Real form, from CI's own body_text for 2025-1.002: "... [2025 c.256
    §6] Note: Sections 3 and 4, chapter 88, Oregon Laws 2025, provide:
    ...". The credit was not the last thing printed, so requiring the
    bracket to reach the true end of the string (the original rule) missed
    it entirely -- the section got no sourceCreditRaw and no
    ors_source_credit row at all, with the credit silently merged into
    bodyText along with its note.
    """

    def test_the_real_1_002_fragment_still_yields_its_own_credit(self):
        markup = (
            "<p><b>1.002 Some catchline.</b> Some statutory text."
            " [2025 c.256 §6] Note: Sections 3 and 4, chapter 88,"
            " Oregon Laws 2025, provide: Sec. 3. No later than September"
            " 15, 2027, the State Court Administrator shall submit a"
            " report.</p>"
        )
        result = parser.parse_chapter(markup, "1")
        section = result["sections"][0]
        self.assertEqual(section["sourceCreditRaw"], "[2025 c.256 §6]")
        self.assertNotIn("2025 c.256", section["bodyText"])
        # The note itself is not dropped -- note extraction is not built
        # yet, so it stays in bodyText rather than disappearing.
        self.assertIn("Sections 3 and 4, chapter 88", section["bodyText"])

    def test_two_consecutive_notes_after_one_credit_are_both_kept(self):
        # Real form: 2025-90.321 prints one credit followed by two separate
        # Note: blocks back to back.
        markup = (
            "<p><b>90.321 Some catchline.</b> Some statutory text."
            " [2025 c.574 §1] Note: 90.321 becomes operative January"
            " 1, 2027. See section 4, chapter 574, Oregon Laws 2025."
            " Note: Section 3, chapter 574, Oregon Laws 2025, provides:"
            " Sec. 3. Before June 1, 2027.</p>"
        )
        result = parser.parse_chapter(markup, "90")
        section = result["sections"][0]
        self.assertEqual(section["sourceCreditRaw"], "[2025 c.574 §1]")
        self.assertIn("becomes operative January", section["bodyText"])
        self.assertIn("Section 3, chapter 574", section["bodyText"])

    def test_an_ordinary_trailing_credit_with_no_note_is_unaffected(self):
        markup = "<p><b>1.010 Some catchline.</b> Some statutory text. [1971 c.743 §1]</p>"
        result = parser.parse_chapter(markup, "1")
        section = result["sections"][0]
        self.assertEqual(section["sourceCreditRaw"], "[1971 c.743 §1]")
        self.assertEqual(section["bodyText"], "Some statutory text.")

    def test_an_earlier_bracket_before_a_note_does_not_steal_the_real_credit(self):
        # A bracket immediately followed by "Note:" earlier in the text must
        # not be mistaken for the section's own trailing credit when a
        # later bracket is the section's actual, truly-trailing credit.
        markup = (
            "<p><b>1.020 Some catchline.</b> Some text mentions [1965 c.1]"
            " Note: an unrelated aside. More statutory text. [1990 c.5 §2]</p>"
        )
        result = parser.parse_chapter(markup, "1")
        section = result["sections"][0]
        self.assertEqual(section["sourceCreditRaw"], "[1990 c.5 §2]")
        self.assertIn("[1965 c.1]", section["bodyText"])


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

    def test_a_stub_led_by_a_plain_citation_is_still_classified(self):
        # Real form observed in chapter 1's own structure-probe sample: a
        # stub-only entry (no catchline, no body) whose bracket opens with a
        # plain enactment citation and states the repeal as a later segment,
        # rather than leading with a disposition keyword.
        markup = "<p><b>1.055 [1959 c.638 §1; repealed by 2015 c.629 §1]</b></p>"
        result = parser.parse_chapter(markup, "1")
        section = result["sections"][0]
        self.assertEqual(section["sectionNumber"], "1.055")
        self.assertEqual(section["status"], "repealed")
        self.assertIsNone(section["catchline"])
        self.assertIsNone(section["bodyText"])
        self.assertEqual(section["sourceCreditRaw"], "[1959 c.638 §1; repealed by 2015 c.629 §1]")


class UnboldedStubDiagnosticTest(unittest.TestCase):
    """Measures stub-shaped lines bold anchoring misses, without acting on them.

    This is deliberately a measurement, not a fix: see
    find_unbolded_stub_lines's docstring for why FINDINGS.md's first "138
    stubs" figure overstates the real gap.
    """

    def test_the_bold_fixture_reports_no_unbolded_stubs(self):
        # Every stub in word_export_chapter.html is bold, so the fixture that
        # exercises ordinary segmentation must report none here.
        self.assertEqual(parsed_fixture()["unboldedStubLines"], [])

    def test_a_genuinely_unbolded_stub_line_is_found(self):
        markup = (
            "<p><b>161.005 Short title.</b> Text. [1971 c.743 §1]</p>"
            "<p>161.025 [Repealed by 1971 c.743 §432]</p>"
        )
        result = parser.parse_chapter(markup, "161")
        self.assertEqual(
            result["unboldedStubLines"],
            [{"number": "161.025", "line": "161.025 [Repealed by 1971 c.743 §432]"}],
        )
        # It is a measurement only: the anchor logic is unchanged, so this
        # stub still produces no section row yet.
        numbers = [item["sectionNumber"] for item in result["sections"]]
        self.assertNotIn("161.025", numbers)

    def test_a_bolded_stub_is_not_double_counted_as_unbolded(self):
        markup = "<p><b>161.025 [Repealed by 1971 c.743 §432]</b></p>"
        result = parser.parse_chapter(markup, "161")
        self.assertEqual(result["unboldedStubLines"], [])

    def test_an_operative_sections_own_formerly_credit_is_not_a_stub_line(self):
        # A credit that opens with "Formerly" or "Amended by" does not itself
        # start a line with a section number, so it must never be mistaken
        # for a stub-shaped line just because it contains the keyword.
        markup = (
            "<p><b>646.190 Definitions.</b> Text here."
            " [Formerly 646.185; repealed by 2009 c.170 §4]</p>"
        )
        result = parser.parse_chapter(markup, "646")
        self.assertEqual(result["unboldedStubLines"], [])

    def test_a_plain_citation_led_stub_is_found_when_unbolded(self):
        # SECTION_STUB_PATTERN was broadened to any bracket-only line, not
        # only one led by a disposition keyword, so this real form (see
        # StatusTest.test_a_stub_led_by_a_plain_citation_is_still_classified)
        # must be found here too when it is not bold.
        markup = "<p>1.055 [1959 c.638 §1; repealed by 2015 c.629 §1]</p>"
        result = parser.parse_chapter(markup, "1")
        self.assertEqual(
            result["unboldedStubLines"],
            [{"number": "1.055", "line": "1.055 [1959 c.638 §1; repealed by 2015 c.629 §1]"}],
        )

    def test_an_unbolded_repeat_of_an_already_anchored_stub_is_not_a_new_finding(self):
        # The broadened pattern raises the same risk bold anchoring exists to
        # avoid: a contents list repeating a stub's own bracket unbolded.
        # A number already claimed by a bold anchor must not be reported
        # again just because the same bracket-shaped text appears elsewhere.
        markup = (
            "<p>1.055 [1959 c.638 §1; repealed by 2015 c.629 §1]</p>"
            "<p><b>1.055 [1959 c.638 §1; repealed by 2015 c.629 §1]</b></p>"
        )
        result = parser.parse_chapter(markup, "1")
        self.assertEqual(result["unboldedStubLines"], [])
        self.assertEqual(len(result["sections"]), 1)


class NewlineSeparatedStubEntriesTest(unittest.TestCase):
    """Consecutive unbolded stubs separated only by a literal source newline.

    Confirmed against real CI output: cross-reference candidates surfaced
    numbers like 1.165/1.167/1.169/1.170 embedded inside chapter 1's 1.160
    body text, yet unboldedStubLineCount reported zero on that same run.
    normalize_chapter_text collapsed the literal newline between each entry
    to a single space -- the same mechanism that (correctly) rejoins wrapped
    prose -- merging every stub after the first into the previous section's
    body text before it could ever become its own line. See
    _collapse_internal_newlines's docstring.
    """

    def test_wrapped_prose_across_a_literal_newline_still_joins(self):
        # The fix must not regress the very case it is modeled on: ordinary
        # statutory text wraps across source lines constantly and must still
        # read as one sentence.
        markup = (
            "<p><b>161.015 General definitions.</b> As used in ORS\n"
            "161.005 to 161.055, unless the context requires otherwise:</p>"
        )
        result = parser.parse_chapter(markup, "161")
        self.assertEqual(
            result["sections"][0]["bodyText"],
            "As used in ORS 161.005 to 161.055, unless the context requires otherwise:",
        )

    def test_consecutive_unbolded_stubs_each_become_their_own_line(self):
        markup = (
            "<p><b>1.160 Procedural rules.</b> Courts shall be governed by "
            "the spirit of the procedural statutes.\n"
            "1.165 [1981 s.s. c.3 §7; renumbered 1.185 in 1999]\n"
            "1.167 [1981 s.s. c.3 §18; renumbered 1.187 in 1999]</p>"
            "<p><b>1.171 Presiding judges.</b> A presiding judge appointed"
            " under ORS 1.003 is presiding judge.</p>"
        )
        result = parser.parse_chapter(markup, "1")
        self.assertEqual(
            result["unboldedStubLines"],
            [
                {"number": "1.165", "line": "1.165 [1981 s.s. c.3 §7; renumbered 1.185 in 1999]"},
                {"number": "1.167", "line": "1.167 [1981 s.s. c.3 §18; renumbered 1.187 in 1999]"},
            ],
        )
        # Real evidence, not yet a fix: turning these into their own section
        # rows (and correctly bounding 1.160's own body/credit against them)
        # is the next step, tracked in ROADMAP.md rather than done here.
        numbers = [item["sectionNumber"] for item in result["sections"]]
        self.assertNotIn("1.165", numbers)
        self.assertNotIn("1.167", numbers)

    def test_span_wrapped_stubs_are_found_even_when_the_newline_is_between_tags(self):
        # The first version of this fix only preserved a newline found
        # *inside* one text run, and measured zero change against the real
        # sample chapters despite the gap being real: real chapters wrap
        # each stub entry in its own bare <span>, so the literal newline
        # (plus indentation) sits *between* two tags as its own whitespace-
        # only run, where a single-run lookahead can never see the stub
        # opening in the *next* run. upcoming_run_opens_a_stub looks past
        # that whitespace-only run to find it.
        markup = (
            "<p><b><span>1.160 Procedural rules.</span></b>"
            "<span> Courts shall be governed by the spirit of the procedural"
            " statutes.</span>\n  "
            "<span>1.165 [1981 s.s. c.3 §7; renumbered 1.185 in 1999]</span>\n  "
            "<span>1.167 [1981 s.s. c.3 §18; renumbered 1.187 in 1999]</span></p>"
            "<p><b>1.171 Presiding judges.</b> A presiding judge appointed"
            " under ORS 1.003 is presiding judge.</p>"
        )
        result = parser.parse_chapter(markup, "1")
        self.assertEqual(
            result["unboldedStubLines"],
            [
                {"number": "1.165", "line": "1.165 [1981 s.s. c.3 §7; renumbered 1.185 in 1999]"},
                {"number": "1.167", "line": "1.167 [1981 s.s. c.3 §18; renumbered 1.187 in 1999]"},
            ],
        )

    def test_span_wrapped_wrapped_prose_still_joins_across_the_tag_boundary(self):
        # The regression this fix must not cause: ordinary statutory text
        # split across two <span> tags, with only whitespace (including a
        # literal newline) between them, must still read as one sentence.
        markup = (
            "<p><b><span>161.015 General definitions.</span></b>"
            "<span> As used in ORS</span>\n  "
            "<span>161.005 to 161.055, unless the context requires otherwise:</span></p>"
        )
        result = parser.parse_chapter(markup, "161")
        self.assertEqual(
            result["sections"][0]["bodyText"],
            "As used in ORS 161.005 to 161.055, unless the context requires otherwise:",
        )


class EmbeddedStubMarkupSampleTest(unittest.TestCase):
    """Raw-markup ground truth, added after two guessed fixes both measured
    zero change against real chapters -- see find_embedded_stub_markup_
    samples's docstring.
    """

    def test_an_unclaimed_embedded_number_captures_its_raw_markup(self):
        markup = (
            "<p><b>1.160 Procedural rules.</b> Courts shall be governed by"
            " the spirit of the procedural statutes.\n"
            "1.165 [1981 s.s. c.3 §7; renumbered 1.185 in 1999]</p>"
        )
        result = parser.parse_chapter(markup, "1")
        self.assertEqual(len(result["embeddedStubMarkupSamples"]), 1)
        sample = result["embeddedStubMarkupSamples"][0]
        self.assertEqual(sample["number"], "1.165")
        self.assertIn("1.165 [1981 s.s. c.3 §7", sample["rawMarkup"])

    def test_a_number_already_anchored_is_not_sampled(self):
        # 1.165 is a real bold stub of its own here, so a later mention of
        # the same "number [" shape elsewhere must not be flagged again.
        markup = (
            "<p><b>1.165 [Renumbered 1.185]</b></p>"
            "<p><b>1.160 Procedural rules.</b> As restated at 1.165 [Renumbered 1.185].</p>"
        )
        result = parser.parse_chapter(markup, "1")
        self.assertEqual(result["embeddedStubMarkupSamples"], [])


class BoldNumberWithFollowingBracketTest(unittest.TestCase):
    """The real published form for a stub-only section, found by dumping raw
    markup (find_embedded_stub_markup_samples) after two newline-collapsing
    fixes each measured zero change against real chapters: the number is
    bold on its own, and its bracket is a separate non-bold span right
    after it in the same paragraph. Neither SECTION_CATCHLINE_PATTERN nor
    SECTION_STUB_PATTERN can match this, since both require the catchline
    or bracket inside the *same* bold run.
    """

    # Verbatim from the real CI dump of chapter 1's actual markup.
    REAL_MARKUP = (
        "<p class=MsoNormal style='margin-bottom:0in;line-height:normal;text-autospace:\r\n"
        "none'><b><span style='font-family:\"Times New Roman\",serif'>      1.055</span></b>"
        "<span\r\nstyle='font-family:\"Times New Roman\",serif'> [1959 c.638 §1; repealed by 2015\r\n"
        "c.212 §2]</span></p>"
    )

    def test_the_real_markup_is_recognized_as_a_repealed_stub(self):
        markup = "<p><b>1.050 An earlier section.</b> Body text. [1971 c.1 §1]</p>" + self.REAL_MARKUP
        result = parser.parse_chapter(markup, "1")
        by_number = {s["sectionNumber"]: s for s in result["sections"]}
        self.assertIn("1.055", by_number)
        section = by_number["1.055"]
        self.assertEqual(section["status"], "repealed")
        self.assertIsNone(section["catchline"])
        self.assertIsNone(section["bodyText"])
        self.assertEqual(section["sourceCreditRaw"], "[1959 c.638 §1; repealed by 2015 c.212 §2]")
        # The preceding section's own text and credit must stay intact.
        self.assertEqual(by_number["1.050"]["bodyText"], "Body text.")
        self.assertEqual(by_number["1.050"]["sourceCreditRaw"], "[1971 c.1 §1]")

    def test_a_run_of_consecutive_real_stubs_are_each_their_own_section(self):
        # Real form: 1.167, 1.169, 1.170 print the same way, one after
        # another, each in its own <p>.
        markup = (
            "<p><b>1.160 Procedural rules.</b> Courts shall be governed by"
            " the spirit of the procedural statutes.</p>"
            "<p class=MsoNormal><b><span>      1.167</span></b>"
            "<span> [1981 s.s. c.3 §18; renumbered\r\n1.187 in 1999]</span></p>"
            "<p class=MsoNormal><b><span>      1.169</span></b>"
            "<span> [1987 c.559 §2; 1989 c.1008 §1;\r\n1995 c.781 §5; repealed by 1995 c.658 §127]</span></p>"
            "<p class=MsoNormal><b><span>      1.170</span></b>"
            "<span> [Repealed by 1981 s.s. c.3 §141]</span></p>"
            "<p><b>1.171 Presiding judges.</b> A presiding judge appointed"
            " under ORS 1.003 is presiding judge.</p>"
        )
        result = parser.parse_chapter(markup, "1")
        by_number = {s["sectionNumber"]: s for s in result["sections"]}
        self.assertEqual(by_number["1.167"]["status"], "renumbered")
        self.assertEqual(by_number["1.167"]["renumberedTo"], "1.187")
        self.assertEqual(by_number["1.169"]["status"], "repealed")
        self.assertEqual(by_number["1.170"]["status"], "repealed")
        # Neither diagnostic should re-flag these now that they are real
        # anchors of their own.
        self.assertEqual(result["unboldedStubLines"], [])
        self.assertEqual(result["embeddedStubMarkupSamples"], [])

    def test_a_long_citation_list_before_the_disposition_is_still_found(self):
        # Real form against chapter 192's own 192.500: a stub-only section
        # can carry many session citations before its final disposition,
        # the same as any operative section's own trailing credit can. A
        # capped lookahead window missed the bracket's close entirely once
        # real CI data showed a credit running past it.
        long_credit = "; ".join(f"197{i} c.{100 + i} §{i}" for i in range(20))
        long_credit += "; repealed by 2015 c.1 §1"
        markup = (
            "<p><b>192.499 An earlier section.</b> Body text. [1971 c.1 §1]</p>"
            f"<p class=MsoNormal><b><span>      192.500</span></b>"
            f"<span> [{long_credit}]</span></p>"
            "<p><b>192.505 Next section.</b> More text. [1971 c.1 §2]</p>"
        )
        result = parser.parse_chapter(markup, "192")
        by_number = {s["sectionNumber"]: s for s in result["sections"]}
        self.assertEqual(by_number["192.500"]["status"], "repealed")
        self.assertEqual(by_number["192.499"]["bodyText"], "Body text.")
        self.assertEqual(result["embeddedStubMarkupSamples"], [])


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


class SourceCreditRowTest(unittest.TestCase):
    """The fixture carries a multi-citation credit and a two-action stub."""

    def setUp(self):
        record = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "sha256": "a" * 64,
            "parsed": parsed_fixture(),
        }
        self.rows = parser.build_rows([record])

    def test_every_section_with_a_credit_yields_credit_rows(self):
        by_section = {}
        for credit in self.rows["sourceCredits"]:
            by_section.setdefault(credit["sectionId"], []).append(credit)
        self.assertEqual(len(by_section["2025-161.005"]), 1)
        self.assertEqual(len(by_section["2025-161.015"]), 3)
        self.assertEqual(len(by_section["2025-161.025"]), 2)

    def test_credit_ids_are_ordered_and_traceable_to_their_section(self):
        credits_015 = [c for c in self.rows["sourceCredits"] if c["sectionId"] == "2025-161.015"]
        self.assertEqual(
            [c["creditId"] for c in credits_015],
            ["2025-161.015-c001", "2025-161.015-c002", "2025-161.015-c003"],
        )
        self.assertEqual([c["ordinal"] for c in credits_015], [1, 2, 3])

    def test_a_stub_credit_carries_its_action_per_citation(self):
        credits_025 = [c for c in self.rows["sourceCredits"] if c["sectionId"] == "2025-161.025"]
        self.assertEqual([c["action"] for c in credits_025], ["amended", "repealed"])

    def test_a_bare_renumbering_reference_is_captured_without_becoming_a_credit(self):
        self.assertEqual(
            self.rows["renumberReferences"],
            [{"sectionId": "2025-161.035", "sectionNumber": "161.045"}],
        )
        renumber_credits = [
            c for c in self.rows["sourceCredits"] if c["sectionId"] == "2025-161.035"
        ]
        self.assertEqual(renumber_credits, [])

    def test_no_credit_segments_go_unparsed_on_the_fixture(self):
        self.assertEqual(self.rows["unparsedCreditSegments"], [])


class CrossReferenceCandidateTest(unittest.TestCase):
    """The fixture's own body text carries a real range mention twice."""

    def setUp(self):
        record = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "sha256": "a" * 64,
            "parsed": parsed_fixture(),
        }
        self.rows = parser.build_rows([record])

    def test_the_fixtures_range_mentions_are_found(self):
        # Both 161.005's and 161.015's body text cite "161.005 to 161.055".
        by_section = {}
        for candidate in self.rows["crossReferenceCandidates"]:
            by_section.setdefault(candidate["sectionId"], []).append(candidate)
        self.assertEqual(
            [c["kind"] for c in by_section["2025-161.005"]], ["range"]
        )
        self.assertEqual(
            by_section["2025-161.005"][0]["text"], "161.005 to 161.055"
        )
        # 161.015's body also carries the wrapped "161.055 (2) does not
        # apply..." continuation line (SegmentationTest establishes that
        # line belongs to 161.015, not a section of its own), which is a
        # real bare mention of 161.055 alongside the range.
        self.assertEqual(
            [c["kind"] for c in by_section["2025-161.015"]], ["range", "section"]
        )

    def test_a_section_with_no_body_text_yields_no_candidates(self):
        # 161.025 is a stub with no bodyText at all.
        for candidate in self.rows["crossReferenceCandidates"]:
            self.assertNotEqual(candidate["sectionId"], "2025-161.025")


class EditorialNoteCandidateTest(unittest.TestCase):
    """build_rows wires ors_section_notes's measurement pass through."""

    def test_the_fixture_carries_no_note_introducers(self):
        record = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "sha256": "a" * 64,
            "parsed": parsed_fixture(),
        }
        rows = parser.build_rows([record])
        self.assertEqual(rows["editorialNoteCandidates"], [])

    def test_a_note_introducer_in_body_text_is_surfaced_with_its_section(self):
        parsed = parsed_fixture()
        parsed["sections"][0]["bodyText"] += (
            " Note: Section 2, chapter 5, Oregon Laws 2020, provides:"
        )
        record = {
            "chapterNumber": "161",
            "chapterSortKey": "000161 ",
            "sha256": "a" * 64,
            "parsed": parsed,
        }
        rows = parser.build_rows([record])
        section_id = f"2025-{parsed['sections'][0]['sectionNumber']}"
        candidates = [
            c for c in rows["editorialNoteCandidates"] if c["sectionId"] == section_id
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["introducer"], "Note:")


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

    def test_a_dangling_credit_reference_is_a_violation(self):
        rows = self._rows()
        rows["sourceCredits"][0]["sectionId"] = "2025-999.999"
        self.assertTrue(
            any("has no section" in item for item in parser.check_referential_integrity(rows))
        )

    def test_an_unknown_credit_action_is_a_violation(self):
        rows = self._rows()
        rows["sourceCredits"][0]["action"] = "probably-fine"
        self.assertTrue(
            any("unknown action" in item for item in parser.check_referential_integrity(rows))
        )

    def test_an_implausible_session_year_is_a_violation(self):
        rows = self._rows()
        rows["sourceCredits"][0]["sessionYear"] = 1500
        self.assertTrue(
            any("implausible session year" in item for item in parser.check_referential_integrity(rows))
        )

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
            # 1 + 3 + 2 citations across the three sections that carry a credit.
            self.assertEqual(report["sourceCreditRowCount"], 6)
            self.assertEqual(report["unparsedCreditSegmentCount"], 0)
            self.assertEqual(len(rows["sourceCredits"]), 6)

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
