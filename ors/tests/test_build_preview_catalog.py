import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_preview_catalog import build_catalog, reference_key, render_catalog
from build_preview_batch import write_batch


class PreviewCatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / "reviews/amendment-previews"
        read = lambda p: json.loads(p.read_text(encoding="utf-8"))
        self.entries = [{"base": read(self.directory/e["base"]), "plan": read(self.directory/e["plan"])}
                        for e in read(self.directory/"catalog.json")["entries"]]
        plans = {reference_key(e["plan"]): e["plan"] for e in self.entries}
        rows = []
        for name in ("2026-amendment-table.json", "2026-amendment-table-expansion.json", "2026-amendment-table-chain.json"):
            review = read(ROOT/"reviews"/name)
            for ref in review["references"]:
                row = {**ref, "sessionYear": review["sessionYear"], "status": "exact-match", "reviewSource": review["source"]}
                plan = plans.get(reference_key(row))
                row["parserProvenance"] = ({"sourceUrl": plan["lawSource"]["url"], "sourceSha256": plan["lawSource"]["sha256"]}
                                           if plan else {"sourceUrl": "https://example.test/unplanned.pdf", "sourceSha256": "0"*64})
                rows.append(row)
        self.proof = {"schemaVersion": 1, "gatePassed": True, "referenceCount": len(rows), "exactMatchCount": len(rows), "rows": rows}

    def build(self, day="2026-09-10"):
        return build_catalog(self.entries, self.proof, day)

    def test_real_collection_exposes_all_unplanned_references(self):
        report = self.build()
        self.assertEqual((report["verifiedReferenceCount"], report["plannedReferenceCount"], report["referencesNeedingTextReview"]), (13, 7, 6))
        self.assertEqual((report["appliedPreviewCount"], report["scheduledPreviewCount"]), (3, 4))
        self.assertFalse(report["allReviewedReferencesHavePlans"])
        missing = [r for r in report["coverage"] if r["status"] == "needs-text-review"]
        self.assertEqual(len(missing), 6)
        self.assertTrue(all(r["operativeDate"] is None and r["effectiveDate"] is None for r in missing))
        self.assertIn("Not reviewed", render_catalog(report))
        section = next(s for s in report["sections"] if s["orsSection"] == "659A.043")
        self.assertFalse(section["baseAvailable"])
        self.assertIsNone(section["latestReviewedPreviewId"])

    def test_deterministic_collection_preserves_inputs_and_chain(self):
        original = copy.deepcopy((self.entries, self.proof))
        report = self.build("2027-07-01")
        self.assertEqual(report["appliedPreviewCount"], 7)
        self.assertEqual(report["scheduledPreviewCount"], 0)
        self.assertEqual((self.entries, self.proof), original)
        self.entries.reverse()
        self.proof["rows"].reverse()
        self.assertEqual(report, self.build("2027-07-01"))
        versions = [p for p in report["batch"]["previews"] if p["sectionNumber"] == "696.370"]
        self.assertEqual(versions[1]["beforeBodyText"], versions[0]["proposedBodyText"])

    def test_future_plan_is_validated_before_early_snapshot_is_published(self):
        self.entries[-1]["plan"]["expectedNormalizedBodySha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "independently reviewed"):
            self.build("2026-03-30")

    def test_labor_plans_change_only_at_reviewed_2027_boundary(self):
        before, after = self.build("2026-12-31"), self.build("2027-01-01")
        self.assertEqual((before["appliedPreviewCount"], before["scheduledPreviewCount"]), (3, 4))
        self.assertEqual((after["appliedPreviewCount"], after["scheduledPreviewCount"]), (6, 1))
        cases = {"653.020": "2026-c2-s1", "653.547": "2026-c2-s2", "653.307": "2026-c7-s1"}
        self.assertTrue(all(p["sectionNumber"] not in cases for p in before["batch"]["previews"]))
        for number, stem in cases.items():
            preview = next(p for p in after["batch"]["previews"] if p["sectionNumber"] == number)
            expected = (self.directory / (stem + "-enacted.txt")).read_text(encoding="utf-8").strip()
            self.assertEqual(" ".join(preview["proposedBodyText"].split()), expected)
            self.assertEqual(preview["effectiveDate"], "2027-01-01")
            self.assertEqual(preview["operativeDate"], "2027-01-01")
            self.assertNotEqual(preview["beforeBodyText"], preview["proposedBodyText"])

    def test_pending_plan_requires_its_own_provenance(self):
        key = reference_key(self.entries[-1]["plan"])
        next(r for r in self.proof["rows"] if reference_key(r) == key)["parserProvenance"]["sourceSha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.build("2026-03-30")

    def test_duplicate_reference_cannot_inflate_coverage(self):
        self.proof["rows"].append(copy.deepcopy(self.proof["rows"][0]))
        self.proof.update(referenceCount=14, exactMatchCount=14)
        with self.assertRaisesRegex(ValueError, "duplicate verified"):
            self.build()

    def test_failed_unplanned_reference_cannot_hide_behind_passed_flag(self):
        self.proof["rows"][1]["status"] = "missing-operative-evidence"
        with self.assertRaisesRegex(ValueError, "counts disagree"):
            self.build()

    def test_count_mismatch_rejected(self):
        self.proof["exactMatchCount"] = 12
        with self.assertRaisesRegex(ValueError, "counts disagree"):
            self.build()

    def test_unverified_plan_rejected(self):
        self.entries[0]["plan"]["sessionLawSection"] = "999"
        with self.assertRaisesRegex(ValueError, "no verified reference"):
            self.build()

    def test_duplicate_plan_for_same_reference_rejected(self):
        self.entries.append(copy.deepcopy(self.entries[0]))
        self.entries[-1]["plan"]["previewId"] = "another-plan"
        with self.assertRaisesRegex(ValueError, "multiple plans"):
            self.build()

    def test_known_unplanned_change_to_previewed_section_remains_visible(self):
        row = copy.deepcopy(self.proof["rows"][0])
        row["sessionLawSection"] = "999"
        self.proof["rows"].append(row)
        self.proof.update(referenceCount=14, exactMatchCount=14)
        section = next(s for s in self.build()["sections"] if s["orsSection"] == row["orsSection"])
        self.assertEqual(section["knownReferencesWithoutPlans"], 1)
        self.assertIsNotNone(section["latestReviewedPreviewId"])

    def test_no_plans_means_review_queue_not_unchanged_law(self):
        self.entries = []
        report = self.build()
        self.assertEqual(report["referencesNeedingTextReview"], 13)
        self.assertEqual(report["batch"]["originalBases"], [])
        self.assertTrue(all(not s["baseAvailable"] for s in report["sections"]))

    def test_reused_batch_directory_cannot_mix_future_and_earlier_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/"batch"
            write_batch(self.build("2027-07-01")["batch"], output)
            original = {p.name: p.read_bytes() for p in output.iterdir()}
            with self.assertRaises(FileExistsError):
                write_batch(self.build("2026-03-30")["batch"], output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, original)

    def test_cli_emits_catalog_and_separate_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            proof = Path(temp)/"verification.json"
            proof.write_text(json.dumps(self.proof), encoding="utf-8")
            output = Path(temp)/"collection"
            command = [sys.executable, str(ROOT/"tools/build_preview_catalog.py"),
                       "--manifest", str(self.directory/"catalog.json"), "--verification", str(proof),
                       "--as-of", "2026-09-10", "--output-dir", str(output)]
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((output/"catalog.json").read_text(encoding="utf-8"))
            self.assertEqual(report, self.build())
            self.assertEqual(len(list((output/"previews").glob("preview-*.md"))), 3)
            self.assertTrue((output/"catalog.md").exists())
            again = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(again.returncode, 0)


if __name__ == "__main__":
    unittest.main()
