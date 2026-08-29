#!/usr/bin/env python3
"""Tests for shared ORS source-text decoding."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ors_text  # noqa: E402


class DeclaredCharsetTest(unittest.TestCase):
    def test_reads_the_word_export_content_type_meta_tag(self):
        data = b'<meta http-equiv=Content-Type content="text/html; charset=windows-1252">'
        self.assertEqual(ors_text.declared_charset(data), "windows-1252")

    def test_reads_the_html5_charset_meta_tag(self):
        self.assertEqual(ors_text.declared_charset(b'<meta charset="UTF-8">'), "utf-8")

    def test_returns_none_when_nothing_is_declared(self):
        self.assertIsNone(ors_text.declared_charset(b"<html><body>text</body></html>"))

    def test_only_the_head_of_the_document_is_scanned(self):
        data = b"x" * 9000 + b'<meta charset="utf-8">'
        self.assertIsNone(ors_text.declared_charset(data))


class DecodeMarkupTest(unittest.TestCase):
    def test_a_declared_windows_encoding_wins_over_the_utf8_default(self):
        # 0xA7 is the section symbol in cp1252 and invalid alone in UTF-8.
        data = "[1971 c.743 §1]".encode("cp1252")
        text, encoding = ors_text.decode_markup(data, "windows-1252")
        self.assertEqual(text, "[1971 c.743 §1]")
        self.assertEqual(encoding, "windows-1252")

    def test_undeclared_windows_bytes_fall_back_rather_than_becoming_replacements(self):
        data = "General rule—see §1".encode("cp1252")
        text, encoding = ors_text.decode_markup(data)
        self.assertEqual(encoding, "cp1252")
        self.assertNotIn("�", text)

    def test_undeclared_utf8_is_decoded_as_utf8(self):
        data = "General rule—see §1".encode("utf-8")
        text, encoding = ors_text.decode_markup(data)
        self.assertEqual(encoding, "utf-8")
        self.assertEqual(text, "General rule—see §1")

    def test_an_unknown_declared_charset_does_not_raise(self):
        text, encoding = ors_text.decode_markup(b"plain text", "not-a-real-charset")
        self.assertEqual(text, "plain text")
        self.assertEqual(encoding, "utf-8")


class NormalizeSpacesTest(unittest.TestCase):
    def test_non_breaking_spaces_become_ordinary_whitespace(self):
        self.assertEqual(
            ors_text.normalize_spaces("161.005    Short title"),
            "161.005    Short title",
        )

    def test_ordinary_text_is_unchanged(self):
        self.assertEqual(ors_text.normalize_spaces("161.005 Short title"), "161.005 Short title")


if __name__ == "__main__":
    unittest.main()
