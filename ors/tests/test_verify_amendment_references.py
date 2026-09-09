import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from verify_amendment_references import verify, verify_reference


class SectionVerificationTests(unittest.TestCase):
    def setUp(self):
        self.review = json.loads((ROOT / "reviews/2026-amendment-table.json").read_text())
        self.ref = self.review["references"][0]
        self.acquired = {"id": "2026orlaw0044", "ok": True, "sha256": "a" * 64,
                         "sourceUrl": "https://example.org/chapter44.pdf"}
        self.evidence = {"evidenceSectionNumber": "471.810", "evidenceAction": "AmendmentAction",
                         "evidenceSource": "OperativeBodyEvidence", "evidenceSectionClause": "19",
                         "evidenceText": "19. ORS 471.810 is amended to read"}
        self.payload = {"year": 2026, "chapter": 44, "bill": {"billType": "HB", "billNumber": 4070},
                        "provenance": {"sourceSha256": "a" * 64, "sourceUrl": self.acquired["sourceUrl"]},
                        "affectedSections": {"amended": ["471.810"], "repealed": []},
                        "validation": {"validationStatus": "Verified", "sectionEvidence": [self.evidence]}}

    def status(self):
        return verify_reference(self.ref, 2026, self.payload, self.acquired)[0]

    def test_exact_operative_match(self):
        self.assertEqual(self.status(), "exact-match")

    def test_title_only_does_not_pass(self):
        self.evidence["evidenceSource"] = "TitleEvidence"
        self.assertEqual(self.status(), "missing-operative-evidence")

    def test_wrong_session_law_section_does_not_pass(self):
        self.evidence["evidenceSectionClause"] = "18"
        self.assertEqual(self.status(), "missing-operative-evidence")

    def test_opposite_action_at_same_clause_is_conflict(self):
        opposite = {**self.evidence, "evidenceAction": "RepealAction"}
        self.payload["validation"]["sectionEvidence"].append(opposite)
        self.assertEqual(self.status(), "conflicting-action")

    def test_other_clause_is_not_a_conflict(self):
        self.payload["validation"]["sectionEvidence"].append(
            {**self.evidence, "evidenceAction": "RepealAction", "evidenceSectionClause": "20"})
        self.assertEqual(self.status(), "exact-match")

    def test_missing_affected_section_is_failure(self):
        self.payload["affectedSections"]["amended"] = []
        self.assertEqual(self.status(), "missing-affected-section")

    def test_wrong_selected_action_is_conflict(self):
        self.payload["affectedSections"] = {"amended": [], "repealed": ["471.810"]}
        self.assertEqual(self.status(), "conflicting-action")

    def test_repeal_reference_can_match(self):
        self.ref = {**self.ref, "action": "R"}
        self.payload["affectedSections"] = {"amended": [], "repealed": ["471.810"]}
        self.evidence["evidenceAction"] = "RepealAction"
        self.assertEqual(self.status(), "exact-match")

    def test_wrong_year_chapter_or_measure_is_failure(self):
        for field, value, expected in [("year", 2025, "identity-mismatch"),
                                       ("chapter", 45, "identity-mismatch"),
                                       ("bill", {}, "measure-mismatch")]:
            with self.subTest(field=field):
                payload = {**self.payload, field: value}
                self.assertEqual(verify_reference(self.ref, 2026, payload, self.acquired)[0], expected)

    def test_provenance_must_match_acquisition(self):
        for field in ("sourceSha256", "sourceUrl"):
            payload = copy.deepcopy(self.payload)
            payload["provenance"][field] = "wrong"
            self.assertEqual(verify_reference(self.ref, 2026, payload, self.acquired)[0], "provenance-mismatch")

    def test_invalid_json_shapes_cannot_pass(self):
        for payload in (None, [], {}, {**self.payload, "validation": []},
                        {**self.payload, "affectedSections": {"amended": "471.810", "repealed": []}}):
            self.assertNotEqual(verify_reference(self.ref, 2026, payload, self.acquired)[0], "exact-match")

    def test_parser_errors_cannot_pass(self):
        self.payload["errors"] = ["failure"]
        self.assertEqual(self.status(), "parser-error")

    def test_missing_and_malformed_files_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "2026orlaw0044.json").write_text("{")
            report = verify([self.review], tmp, {"documents": [self.acquired]})
        self.assertFalse(report["gatePassed"])
        self.assertEqual(report["statusCounts"], {"invalid-result": 1, "missing-result": 6})

    def test_duplicate_review_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "duplicate reviewed"):
                verify([self.review, self.review], tmp, {"documents": []})


if __name__ == "__main__":
    unittest.main()
