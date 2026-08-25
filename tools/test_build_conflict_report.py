#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class ConflictReportTest(unittest.TestCase):
    def test_mismatch_becomes_review_case_with_parser_and_lc_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = root / "results"
            results.mkdir()
            manifest = {
                "documents": [{
                    "id": "case-1",
                    "sourceUrl": "https://example.test/law.pdf",
                    "reviewBasis": "manual review",
                    "expected": {
                        "year": 2026,
                        "chapter": 108,
                        "bill": {"billType": "HB", "billNumber": 1},
                        "effectiveDate": "2026-01-01",
                        "affectedSections": {"amended": ["455.628"], "repealed": []},
                    },
                }]
            }
            actual = {
                "year": 2026,
                "chapter": 108,
                "bill": {"billType": "HB", "billNumber": 1},
                "effectiveDate": "2026-01-01",
                "affectedSections": {"amended": ["455.629"], "repealed": []},
                "validation": {
                    "validationStatus": "Conflict",
                    "sectionEvidence": [{
                        "evidenceSection": "455.629",
                        "evidenceAction": "amended",
                        "evidenceSource": "OperativeBody",
                        "evidenceText": "SECTION 1. ORS 455.629 is amended to read:",
                    }],
                },
            }
            quality = {
                "gatePassed": False,
                "releaseCertifying": False,
                "documents": [{"id": "case-1", "metadataExactMatch": True}],
            }
            lc_csv = (
                "ors_section,action,oregon_laws_chapter,oregon_laws_section,source_url,source_year,source_volume\n"
                "455.628,amended,108,16,https://example.test/lc.pdf,2026,13\n"
            )
            (root / "manifest.json").write_text(json.dumps(manifest))
            (results / "case-1.json").write_text(json.dumps(actual))
            (root / "quality.json").write_text(json.dumps(quality))
            (root / "lc.csv").write_text(lc_csv)

            script = Path(__file__).with_name("build_conflict_report.py")
            subprocess.run([
                "python3", str(script),
                "--manifest", str(root / "manifest.json"),
                "--results-dir", str(results),
                "--quality-report", str(root / "quality.json"),
                "--lc-csv", str(root / "lc.csv"),
                "--report", str(root / "report.json"),
            ], check=True, capture_output=True, text=True)

            report = json.loads((root / "report.json").read_text())
            self.assertEqual(report["reviewCaseCount"], 1)
            case = report["cases"][0]
            self.assertEqual(case["falsePositives"], [["amended", "455.629"]])
            self.assertEqual(case["falseNegatives"], [["amended", "455.628"]])
            self.assertEqual(len(case["parserEvidence"]), 1)
            self.assertEqual(len(case["legislativeCounselEvidence"]), 1)


if __name__ == "__main__":
    unittest.main()
