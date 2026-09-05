import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "tools" / "diff_ors_editions.py"
spec = importlib.util.spec_from_file_location("diff_ors_editions", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def row(number, *, catchline="Same.", body="text", status="operative", renumbered_to=None, edition="2025"):
    return {
        "section_id": f"{edition}-{number}",
        "section_number": number,
        "catchline": catchline,
        "body_text": body,
        "status": status,
        "renumbered_to": renumbered_to,
    }


class EditionDiffTests(unittest.TestCase):
    def test_classifies_added_removed_changed_and_unchanged(self):
        before = [
            row("1.010"),
            row("1.020", body="old"),
            row("1.030", status="operative"),
        ]
        after = [
            row("1.010", edition="2027"),
            row("1.020", body="new", edition="2027"),
            row("1.040", edition="2027"),
        ]
        report = mod.diff_sections(before, after, 2025, 2027)
        self.assertTrue(report["valid"])
        self.assertEqual(report["addedCount"], 1)
        self.assertEqual(report["removedCount"], 1)
        self.assertEqual(report["changedCount"], 1)
        self.assertEqual(report["unchangedCount"], 1)
        self.assertEqual(report["added"][0]["sectionNumber"], "1.040")
        self.assertEqual(report["removed"][0]["sectionNumber"], "1.030")
        self.assertEqual(report["changed"][0]["sectionNumber"], "1.020")
        self.assertEqual(report["changed"][0]["changes"]["body_text"], {"before": "old", "after": "new"})

    def test_surrogate_section_id_change_alone_is_not_statutory_change(self):
        before = [row("2.010", edition="2025")]
        after = [row("2.010", edition="2027")]
        report = mod.diff_sections(before, after, 2025, 2027)
        self.assertEqual(report["changedCount"], 0)
        self.assertEqual(report["unchangedSectionNumbers"], ["2.010"])

    def test_tracks_status_and_renumber_destination(self):
        before = [row("3.010")]
        after = [row("3.010", status="renumbered", renumbered_to="3.020", edition="2027")]
        changes = mod.diff_sections(before, after, 2025, 2027)["changed"][0]["changes"]
        self.assertIn("status", changes)
        self.assertIn("renumbered_to", changes)

    def test_duplicate_section_numbers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate section_number"):
            mod.diff_sections([row("4.010"), row("4.010")], [], 2025, 2027)

    def test_reconciliation_is_explicitly_not_run(self):
        report = mod.diff_sections([], [], 2025, 2027)
        self.assertEqual(report["reconciliation"]["status"], "not-run")


if __name__ == "__main__":
    unittest.main()
