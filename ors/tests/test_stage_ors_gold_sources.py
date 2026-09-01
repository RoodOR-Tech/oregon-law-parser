import json
import tempfile
import unittest
from pathlib import Path

from ors.tools import stage_ors_gold_sources as staging


class StageOrsGoldSourcesTests(unittest.TestCase):
    def write(self, directory, name, value):
        path = Path(directory) / name
        path.write_text(json.dumps(value))
        return path

    def base_selection(self):
        return {
            "selectionStatus": "frozen-before-parser-evaluation",
            "editionYear": 2025,
            "chapters": [
                {"chapterNumber": "12", "sourceUrl": "https://example/ors012.html"},
                {"chapterNumber": "659A", "sourceUrl": "https://example/ors659A.html"},
            ],
        }

    def base_acquisition(self):
        return {
            "valid": True,
            "chapters": [
                {"chapterNumber": "12", "ok": True, "sourceUrl": "https://example/ors012.html", "sourceFormat": "html", "sha256": "a" * 64, "bytes": 10, "httpStatus": 200, "retrievedAt": "2026-01-01T00:00:00Z"},
                {"chapterNumber": "659A", "ok": True, "sourceUrl": "https://example/ors659A.html", "sourceFormat": "html", "sha256": "b" * 64, "bytes": 20, "httpStatus": 200, "retrievedAt": "2026-01-01T00:00:00Z"},
            ],
        }

    def test_exact_selection_is_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = self.write(tmp, "selection.json", self.base_selection())
            acquisition = self.write(tmp, "acquisition.json", self.base_acquisition())
            output = Path(tmp) / "registry.json"
            old = __import__("sys").argv
            try:
                __import__("sys").argv = ["stage", "--selection", str(selection), "--acquisition", str(acquisition), "--output", str(output)]
                self.assertEqual(staging.main(), 0)
            finally:
                __import__("sys").argv = old
            registry = json.loads(output.read_text())
            self.assertTrue(registry["valid"])
            self.assertEqual(registry["documentCount"], 2)

    def test_acquisition_coverage_must_match_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = self.base_selection()
            acquisition = self.base_acquisition()
            acquisition["chapters"] = acquisition["chapters"][:1]
            selection_path = self.write(tmp, "selection.json", selection)
            acquisition_path = self.write(tmp, "acquisition.json", acquisition)
            old = __import__("sys").argv
            try:
                __import__("sys").argv = ["stage", "--selection", str(selection_path), "--acquisition", str(acquisition_path), "--output", str(Path(tmp) / "out.json")]
                with self.assertRaisesRegex(ValueError, "coverage does not exactly match"):
                    staging.main()
            finally:
                __import__("sys").argv = old

    def test_url_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            selection = self.base_selection()
            acquisition = self.base_acquisition()
            acquisition["chapters"][0]["sourceUrl"] = "https://example/other.html"
            selection_path = self.write(tmp, "selection.json", selection)
            acquisition_path = self.write(tmp, "acquisition.json", acquisition)
            old = __import__("sys").argv
            try:
                __import__("sys").argv = ["stage", "--selection", str(selection_path), "--acquisition", str(acquisition_path), "--output", str(Path(tmp) / "out.json")]
                with self.assertRaisesRegex(ValueError, "URL differs"):
                    staging.main()
            finally:
                __import__("sys").argv = old


if __name__ == "__main__":
    unittest.main()
