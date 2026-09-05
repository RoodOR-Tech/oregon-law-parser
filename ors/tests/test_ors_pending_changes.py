#!/usr/bin/env python3
"""Tests for increment 6's pending-change notice extraction.

Every line here is a real, verbatim fragment confirmed against the frozen
increment 5 gold chapter bytes (183, 471, 659A print these notices; 12 and
105 print neither) -- see ors_pending_changes.py's module docstring.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from parse_ors_chapter import line_spans  # noqa: E402
from ors_pending_changes import find_pending_change_notices  # noqa: E402


def lines_for(text):
    return list(line_spans(text))


class NoNoticeTest(unittest.TestCase):
    def test_ordinary_text_yields_no_rows(self):
        self.assertEqual(find_pending_change_notices(lines_for("An ordinary line of statutory text.")), [])

    def test_empty_text_yields_no_rows(self):
        self.assertEqual(find_pending_change_notices(lines_for("")), [])


class AmendedOrRepealedElsewhereTest(unittest.TestCase):
    # Real fragment from chapter 471 and chapter 659A.
    NOTICE = (
        "ORS sections in this chapter were amended or repealed by the "
        "Legislative Assembly during its 2026 regular session. See the "
        "table of ORS sections amended or repealed during the 2026 "
        "regular session: 2026 A&R Tables"
    )

    def test_one_row_with_no_named_chapter(self):
        result = find_pending_change_notices(lines_for(self.NOTICE))
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row["changeKind"], "amended_or_repealed_elsewhere")
        self.assertEqual(row["sessionYear"], 2026)
        self.assertIsNone(row["sessionLawChapter"])
        self.assertEqual(row["noticeText"], self.NOTICE)

    def test_offsets_span_the_whole_line(self):
        padded = f"Something before.\n{self.NOTICE}"
        result = find_pending_change_notices(lines_for(padded))
        self.assertEqual(len(result), 1)
        start, end = result[0]["charOffsetStart"], result[0]["charOffsetEnd"]
        self.assertEqual(padded[start:end], self.NOTICE)


class NewSeriesSectionTest(unittest.TestCase):
    # Real fragment from chapter 183 (three named chapters).
    NOTICE = (
        "New sections of law were added by legislative action to this ORS "
        "chapter or to a series within this ORS chapter by the Legislative "
        "Assembly during its 2026 regular session. See sections in the "
        "following 2026 Oregon Laws chapters: 2026 Session Laws 0050; 2026 "
        "Session Laws 0104; 2026 Session Laws 0105"
    )

    def test_one_row_per_named_chapter(self):
        result = find_pending_change_notices(lines_for(self.NOTICE))
        self.assertEqual([row["sessionLawChapter"] for row in result], [50, 104, 105])
        for row in result:
            self.assertEqual(row["changeKind"], "new_series_section")
            self.assertEqual(row["sessionYear"], 2026)
            self.assertEqual(row["noticeText"], self.NOTICE)

    # Real fragment from chapter 659A (single named chapter).
    def test_a_single_named_chapter(self):
        notice = (
            "New sections of law were added by legislative action to this "
            "ORS chapter or to a series within this ORS chapter by the "
            "Legislative Assembly during its 2026 regular session. See "
            "sections in the following 2026 Oregon Laws chapters: 2026 "
            "Session Laws 0057"
        )
        result = find_pending_change_notices(lines_for(notice))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sessionLawChapter"], 57)


class NewCompiledSectionTest(unittest.TestCase):
    # Real fragment from chapter 659A (two named chapters).
    NOTICE = (
        "New sections of law were enacted by the Legislative Assembly "
        "during its 2026 regular session and pertain to or are likely to "
        "be compiled in this ORS chapter. See sections in the following "
        "2026 Oregon Laws chapters: 2026 Session Laws 0093; 2026 Session "
        "Laws 0126"
    )

    def test_one_row_per_named_chapter(self):
        result = find_pending_change_notices(lines_for(self.NOTICE))
        self.assertEqual([row["sessionLawChapter"] for row in result], [93, 126])
        for row in result:
            self.assertEqual(row["changeKind"], "new_compiled_section")
            self.assertEqual(row["sessionYear"], 2026)


class AllThreeNoticesTest(unittest.TestCase):
    def test_a_chapter_printing_all_three_notices_yields_every_row_in_order(self):
        text = "\n".join([
            AmendedOrRepealedElsewhereTest.NOTICE,
            NewSeriesSectionTest.NOTICE,
            NewCompiledSectionTest.NOTICE,
        ])
        result = find_pending_change_notices(lines_for(text))
        kinds = [row["changeKind"] for row in result]
        self.assertEqual(
            kinds,
            [
                "amended_or_repealed_elsewhere",
                "new_series_section", "new_series_section", "new_series_section",
                "new_compiled_section", "new_compiled_section",
            ],
        )


if __name__ == "__main__":
    unittest.main()
