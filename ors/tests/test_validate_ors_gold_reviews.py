import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "ors" / "tools" / "validate_ors_gold_reviews.py"
spec = importlib.util.spec_from_file_location("validate_ors_gold_reviews", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GoldReviewValidationTests(unittest.TestCase):
    def setUp(self):
        self.provenance = json.loads((ROOT / "ors/gold/reviews/source-staging-provenance.json").read_text())
        self.review = json.loads((ROOT / "ors/gold/reviews/chapter-12.json").read_text())

    def test_chapter_12_review_matches_pre_evaluation_source(self):
        self.assertEqual(module.validate_review(self.review, self.provenance), [])
        self.assertEqual(self.review["expected"]["sectionCount"], 52)
        self.assertEqual(self.review["expected"]["statusCounts"]["repealed"], 3)

    def test_source_hash_drift_is_rejected(self):
        review = copy.deepcopy(self.review)
        review["sourceSha256"] = "0" * 64
        errors = module.validate_review(review, self.provenance)
        self.assertTrue(any("sourceSha256 differs" in error for error in errors))

    def test_parser_consultation_is_rejected(self):
        review = copy.deepcopy(self.review)
        review["reviewMethod"]["parserOutputConsulted"] = True
        errors = module.validate_review(review, self.provenance)
        self.assertTrue(any("parser output" in error for error in errors))

    def test_duplicate_section_is_rejected(self):
        review = copy.deepcopy(self.review)
        review["expected"]["sections"].append(copy.deepcopy(review["expected"]["sections"][0]))
        review["expected"]["sectionCount"] += 1
        review["expected"]["statusCounts"]["operative"] += 1
        errors = module.validate_review(review, self.provenance)
        self.assertIn("duplicate section numbers", errors)


if __name__ == "__main__":
    unittest.main()
