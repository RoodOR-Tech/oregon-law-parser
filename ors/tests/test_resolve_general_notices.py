import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from resolve_general_notices import resolve, review_index


class GeneralNoticeTests(unittest.TestCase):
    def setUp(self):
        self.review = json.loads((ROOT / "reviews/2026-amendment-table.json").read_text())
        self.pending = [{"pending_change_id": "p" + chapter,
                         "chapter_id": "2025-" + chapter, "session_year": 2026,
                         "session_law_chapter": None,
                         "change_kind": "amended_or_repealed_elsewhere"}
                        for chapter in ("471", "659A")]
        self.results = {(2026, chapter): {"status": "parsed", "path": str(chapter)}
                        for chapter in (44, 109, 126, 57)}

    def test_reviewed_references_match_and_input_notices_are_preserved(self):
        before = copy.deepcopy(self.pending)
        report = resolve(self.pending, self.review, self.results)
        self.assertEqual(report["resolvedNoticeCount"], 2)
        self.assertEqual(report["matchedReferenceCount"], 7)
        self.assertEqual(self.pending, before)
        self.assertEqual(report["rows"][0]["references"][0]["orsSection"], "471.810")

    def test_missing_one_law_keeps_notice_unresolved(self):
        del self.results[(2026, 109)]
        report = resolve(self.pending, self.review, self.results)
        self.assertEqual(report["resolvedNoticeCount"], 1)
        self.assertEqual(report["matchedReferenceCount"], 3)
        self.assertEqual(report["rows"][1]["references"][0]["status"], "missing-session-result")

    def test_parser_failure_cannot_resolve_notice(self):
        self.results[(2026, 44)]["status"] = "parser-error"
        report = resolve(self.pending, self.review, self.results)
        self.assertEqual(report["rows"][0]["status"], "unresolved")
        self.assertEqual(report["rows"][0]["references"][0]["status"], "matched-parser-error")

    def test_other_session_or_unreviewed_chapter_is_not_inferred(self):
        self.pending[0]["session_year"] = 2027
        self.pending[1]["chapter_id"] = "2025-659"
        report = resolve(self.pending, self.review, self.results)
        self.assertEqual(report["unresolvedNoticeCount"], 2)
        self.assertEqual(report["matchedReferenceCount"], 0)

    def test_specific_notice_is_not_reinterpreted(self):
        self.pending[0]["session_law_chapter"] = 44
        self.assertEqual(resolve(self.pending, self.review, self.results)["generalNoticeCount"], 1)

    def test_duplicate_reference_is_rejected(self):
        self.review["references"].append(self.review["references"][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            review_index(self.review)

    def test_addition_is_not_an_amendment_or_repeal(self):
        self.review["references"][0]["action"] = "Add"
        with self.assertRaisesRegex(ValueError, "invalid"):
            review_index(self.review)

    def test_source_hash_is_required(self):
        del self.review["source"]["sha256"]
        with self.assertRaisesRegex(ValueError, "source"):
            review_index(self.review)


if __name__ == "__main__":
    unittest.main()
