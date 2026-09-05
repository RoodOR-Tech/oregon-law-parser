import unittest

from ors.tools.ors_pending_changes import parse_pending_changes


class PendingChangeParserTest(unittest.TestCase):
    def test_real_chapter_659a_notice_shapes(self):
        markup = '''
        <html><body>
        <p>ORS sections in this chapter were amended or repealed by the Legislative Assembly during its 2026 regular session. See the table of ORS sections amended or repealed during the 2026 regular session: <a>2026 A&amp;R Tables</a></p>
        <p>New sections of law were added by legislative action to this ORS chapter or to a series within this ORS chapter by the Legislative Assembly during its 2026 regular session. See sections in the following 2026 Oregon Laws chapters: <a>2026 Session Laws 0057</a></p>
        <p>New sections of law were enacted by the Legislative Assembly during its 2026 regular session and pertain to or are likely to be compiled in this ORS chapter. See sections in the following 2026 Oregon Laws chapters: <a>2026 Session Laws 0093</a>; <a>2026 Session Laws 0126</a></p>
        <h2>2025 EDITION</h2>
        <p>659A.001 Definitions</p>
        </body></html>
        '''
        rows = parse_pending_changes(markup, "2025", "659A")
        self.assertEqual(4, len(rows))
        self.assertEqual(
            [
                ("amended_or_repealed", None),
                ("added_to_chapter_or_series", 57),
                ("likely_compiled_in_chapter", 93),
                ("likely_compiled_in_chapter", 126),
            ],
            [(row["notice_kind"], row["session_law_chapter"]) for row in rows],
        )
        self.assertTrue(all(row["session_year"] == 2026 for row in rows))
        self.assertTrue(all(row["session_kind"] == "regular" for row in rows))
        self.assertEqual(
            ["2025-659A-pc001", "2025-659A-pc002", "2025-659A-pc003", "2025-659A-pc004"],
            [row["pending_change_id"] for row in rows],
        )

    def test_body_references_are_not_notices(self):
        markup = '''<h2>2025 EDITION</h2><p>New sections of law were enacted by the Legislative Assembly during its 2026 regular session. 2026 Session Laws 0093</p>'''
        self.assertEqual([], parse_pending_changes(markup, "2025", "659A"))

    def test_notice_without_session_identity_fails(self):
        markup = '''<p>New sections of law were enacted by the Legislative Assembly and pertain to or are likely to be compiled in this ORS chapter. See sections in the following 2026 Oregon Laws chapters: 2026 Session Laws 0093</p><h2>2025 EDITION</h2>'''
        with self.assertRaises(ValueError):
            parse_pending_changes(markup, "2025", "659A")


if __name__ == "__main__":
    unittest.main()
