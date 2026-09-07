import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "reconcile_pending_changes.py"
spec = importlib.util.spec_from_file_location("reconcile_pending_changes", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PendingChangeReconciliationTests(unittest.TestCase):
    def test_matches_parsed_result_and_preserves_non_specific_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026orlaw0057.json").write_text(json.dumps({"amendment": []}), encoding="utf-8")
            index = mod.index_session_results(root)
            report = mod.reconcile([
                {
                    "pending_change_id": "2025-659A-pc001",
                    "chapter_id": "2025-659A",
                    "change_kind": "new_series_section",
                    "session_year": 2026,
                    "session_law_chapter": 57,
                },
                {
                    "pending_change_id": "2025-659A-pc002",
                    "chapter_id": "2025-659A",
                    "change_kind": "amended_or_repealed_elsewhere",
                    "session_year": 2026,
                    "session_law_chapter": None,
                },
            ], index)
            self.assertEqual(report["matchedParsedCount"], 1)
            self.assertEqual(report["nonSpecificNoticeCount"], 1)
            self.assertTrue(report["allChapterSpecificNoticesResolved"])
            self.assertEqual(report["rows"][0]["reconciliation_status"], "matched-parsed")
            self.assertEqual(report["rows"][1]["reconciliation_status"], "non-specific-notice")
            # change_kind is the real ors_chapter_pending_change column name
            # (see SCHEMA.md and build_ors_relational.py); it must survive
            # into the report rather than being read under a name -- like an
            # earlier "notice_kind" -- that never matches the real rows.
            self.assertEqual(report["rows"][0]["change_kind"], "new_series_section")
            self.assertEqual(report["rows"][1]["change_kind"], "amended_or_repealed_elsewhere")

    def test_missing_result_is_explicit_and_not_treated_as_parser_failure(self):
        report = mod.reconcile([
            {
                "pending_change_id": "pc",
                "chapter_id": "2025-659A",
                "change_kind": "new_compiled_section",
                "session_year": 2026,
                "session_law_chapter": 93,
            }
        ], {})
        self.assertEqual(report["missingSessionResultCount"], 1)
        self.assertTrue(report["completeForAvailableSessionResults"])
        self.assertFalse(report["allChapterSpecificNoticesResolved"])

    def test_parser_error_is_distinct_from_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026orlaw0126.json").write_text(json.dumps({"errors": [{"kind": "x"}]}), encoding="utf-8")
            report = mod.reconcile([
                {
                    "pending_change_id": "pc",
                    "chapter_id": "2025-659A",
                    "change_kind": "new_compiled_section",
                    "session_year": 2026,
                    "session_law_chapter": 126,
                }
            ], mod.index_session_results(root))
            self.assertEqual(report["matchedParserErrorCount"], 1)
            self.assertFalse(report["completeForAvailableSessionResults"])
            self.assertFalse(report["allChapterSpecificNoticesResolved"])

    def test_invalid_json_is_parser_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "2026orlaw0057.json").write_text("{", encoding="utf-8")
            indexed = mod.index_session_results(root)
            self.assertEqual(indexed[(2026, 57)]["status"], "invalid-json")

    def test_chapter_specific_notice_requires_integer_identity(self):
        with self.assertRaisesRegex(ValueError, "requires integer"):
            mod.reconcile([
                {
                    "pending_change_id": "pc",
                    "chapter_id": "2025-659A",
                    "change_kind": "new_series_section",
                    "session_year": "2026",
                    "session_law_chapter": 57,
                }
            ], {})


if __name__ == "__main__":
    unittest.main()
