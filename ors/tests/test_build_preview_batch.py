import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_preview_batch import build_batch
from build_amendment_preview import digest, row_digest


class PreviewBatchTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / "reviews/amendment-previews"
        read = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
        self.entries = [{"base": read(e["base"]), "plan": read(e["plan"])} for e in read("batch.json")["entries"]]

    def proof(self, entries):
        keys = ("orsSection", "sessionYear", "sessionLawChapter", "sessionLawSection", "action", "measure")
        return {"gatePassed": True, "rows": [{**{k: e["plan"][k] for k in keys}, "status": "exact-match",
            "parserProvenance": {"sourceSha256": e["plan"]["lawSource"]["sha256"],
                                 "sourceUrl": e["plan"]["lawSource"]["url"]}} for e in entries]}

    def build(self, entries=None, as_of="2026-06-05"):
        entries = self.entries if entries is None else entries
        return build_batch(entries, self.proof(entries), as_of)

    def chain(self):
        first = copy.deepcopy(self.entries[0])
        second = copy.deepcopy(first)
        a, b = first["plan"], second["plan"]
        b.update(previewId="synthetic-successor", predecessorPreviewId=a["previewId"],
                 sessionLawSection="20", operativeDate="2026-07-01")
        derived = copy.deepcopy(first["base"]["section"])
        derived["body_text"] = derived["body_text"].replace(a["edit"]["old"], a["edit"]["new"])
        b["baseRowSha256"] = row_digest(derived)
        b["edit"] = {"old": a["edit"]["new"], "new": "Synthetic successor account", "occurrences": 1}
        b["expectedNormalizedBodySha256"] = digest(" ".join(derived["body_text"].replace(
            b["edit"]["old"], b["edit"]["new"]).split()))
        return [first, second]

    def test_real_previews_are_deterministic_and_preserve_bases(self):
        original = copy.deepcopy(self.entries)
        a, b = self.build(), self.build(list(reversed(self.entries)))
        self.assertEqual(a, b)
        self.assertEqual(self.entries, original)
        self.assertEqual([p["sectionNumber"] for p in a["previews"]], ["659A.410", "471.810"])
        self.assertEqual(a["previewCount"], 2)

    def test_as_of_date_keeps_future_plans_pending(self):
        self.assertEqual(self.build(as_of="2026-04-06")["previewCount"], 0)
        report = self.build(as_of="2026-04-07")
        self.assertEqual(report["previewCount"], 1)
        self.assertEqual(report["pendingCount"], 1)

    def test_reviewed_successor_preserves_all_versions(self):
        chain = self.chain()
        report = self.build(list(reversed(chain)), "2026-07-01")
        self.assertEqual(report["previewCount"], 2)
        self.assertEqual(report["previews"][1]["beforeBodyText"], report["previews"][0]["proposedBodyText"])
        self.assertIn(chain[0]["plan"]["edit"]["new"], report["previews"][0]["proposedBodyText"])
        self.assertEqual(report["currentPreviewBySection"]["2025-471.810"], "synthetic-successor")

    def test_successor_with_old_base_hash_is_rejected(self):
        chain = self.chain()
        chain[1]["plan"]["baseRowSha256"] = chain[0]["plan"]["baseRowSha256"]
        with self.assertRaisesRegex(ValueError, "base row changed"):
            self.build(chain, "2026-07-01")

    def test_unordered_same_section_plans_are_rejected(self):
        chain = self.chain()
        del chain[1]["plan"]["predecessorPreviewId"]
        with self.assertRaisesRegex(ValueError, "unordered"):
            self.build(chain)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate preview"):
            self.build([self.entries[0], self.entries[0]])

    def test_missing_predecessor_is_rejected(self):
        chain = self.chain()
        with self.assertRaisesRegex(ValueError, "missing predecessor"):
            self.build(chain[1:])

    def test_backwards_date_is_rejected(self):
        chain = self.chain()
        chain[1]["plan"]["operativeDate"] = "2026-04-01"
        with self.assertRaisesRegex(ValueError, "precedes predecessor"):
            self.build(chain)

    def test_cross_section_predecessor_is_rejected(self):
        self.entries[0]["plan"]["predecessorPreviewId"] = self.entries[1]["plan"]["previewId"]
        with self.assertRaisesRegex(ValueError, "another section"):
            self.build()

    def test_cycle_is_rejected(self):
        chain = self.chain()
        chain[0]["plan"]["predecessorPreviewId"] = chain[1]["plan"]["previewId"]
        chain[1]["plan"]["operativeDate"] = chain[0]["plan"]["operativeDate"]
        with self.assertRaisesRegex(ValueError, "cyclic"):
            self.build(chain)

    def test_branch_is_rejected(self):
        chain = self.chain()
        third = copy.deepcopy(chain[1])
        third["plan"]["previewId"] = "other-successor"
        with self.assertRaisesRegex(ValueError, "branched"):
            self.build(chain + [third])


if __name__ == "__main__":
    unittest.main()
