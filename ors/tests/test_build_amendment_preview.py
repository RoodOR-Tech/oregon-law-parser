import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_amendment_preview import build_preview, row_digest


class AmendmentPreviewTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / "reviews/amendment-previews"
        self.base = json.loads((directory / "471810-base.json").read_text(encoding="utf-8"))
        self.plan = json.loads((directory / "2026-c44-s19.json").read_text(encoding="utf-8"))
        keys = ("orsSection", "sessionYear", "sessionLawChapter", "sessionLawSection", "action", "measure")
        self.verification = {"gatePassed": True, "rows": [{**{k: self.plan[k] for k in keys},
            "status": "exact-match", "parserProvenance": {
                "sourceSha256": self.plan["lawSource"]["sha256"],
                "sourceUrl": self.plan["lawSource"]["url"]}}]}

    def build(self, as_of="2026-06-05"):
        return build_preview(self.base, self.plan, self.verification, as_of)

    def test_reviewed_replacement_preserves_original(self):
        before = copy.deepcopy(self.base)
        report = self.build()
        self.assertEqual(self.base, before)
        self.assertEqual(report["status"], "reviewed-preview")
        self.assertIn(self.plan["edit"]["old"], report["beforeBodyText"])
        self.assertNotIn(self.plan["edit"]["old"], report["proposedBodyText"])
        self.assertEqual(report["proposedBodyText"].count(self.plan["edit"]["new"]), 1)
        self.assertNotIn("char_offset_start", report)

    def test_before_effective_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not yet operative"):
            self.build("2026-06-04")

    def test_later_operative_date_is_respected(self):
        self.plan["operativeDate"] = "2027-01-01"
        with self.assertRaisesRegex(ValueError, "not yet operative"):
            self.build()

    def test_changed_base_text_or_catchline_is_rejected(self):
        for field in ("body_text", "catchline"):
            base = copy.deepcopy(self.base)
            base["section"][field] += " changed"
            with self.assertRaisesRegex(ValueError, "base row changed"):
                build_preview(base, self.plan, self.verification, "2026-06-05")

    def test_changed_source_is_rejected(self):
        self.verification["rows"][0]["parserProvenance"]["sourceSha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "amendment source changed"):
            self.build()

    def test_mismatched_reference_is_rejected(self):
        self.verification["rows"][0]["sessionLawSection"] = "20"
        with self.assertRaisesRegex(ValueError, "exact reviewed reference"):
            self.build()

    def test_failed_verification_is_rejected(self):
        self.verification["gatePassed"] = False
        with self.assertRaisesRegex(ValueError, "gate did not pass"):
            self.build()

    def test_duplicate_proof_is_rejected(self):
        self.verification["rows"] *= 2
        with self.assertRaisesRegex(ValueError, "exact reviewed reference"):
            self.build()

    def test_unreviewed_replacement_is_rejected(self):
        self.plan["edit"]["new"] = "Unreviewed account"
        with self.assertRaisesRegex(ValueError, "independently reviewed"):
            self.build()

    def test_ambiguous_replacement_is_rejected(self):
        self.base["section"]["body_text"] += " " + self.plan["edit"]["old"]
        self.plan["baseRowSha256"] = row_digest(self.base["section"])
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.build()


if __name__ == "__main__":
    unittest.main()
