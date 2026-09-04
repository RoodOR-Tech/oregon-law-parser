import json
import tempfile
import unittest
from pathlib import Path

from ors.tools import gold_precision_recall as gpr


class ComparisonTests(unittest.TestCase):
    """Unit-level tests for compare_chapter/aggregate, no files involved."""

    def expected_doc(self, sections):
        return {
            "chapterNumber": "12",
            "editionYear": 2025,
            "expectedSections": sections,
        }

    def test_a_perfect_match_scores_1_0_on_every_metric(self):
        expected = self.expected_doc([
            {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
            {"sectionNumber": "12.020", "catchline": None, "status": "repealed"},
        ])
        actual = {
            "12.010": {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
            "12.020": {"sectionNumber": "12.020", "catchline": None, "status": "repealed"},
        }
        result = gpr.compare_chapter(expected, actual)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["catchlineExactMatchRate"], 1.0)
        self.assertEqual(result["statusExactMatchRate"], 1.0)
        self.assertEqual(result["falseNegatives"], 0)
        self.assertEqual(result["falsePositives"], 0)

    def test_a_section_the_parser_misses_is_a_false_negative_and_lowers_recall(self):
        expected = self.expected_doc([
            {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
            {"sectionNumber": "12.020", "catchline": "Second.", "status": "operative"},
        ])
        actual = {
            "12.010": {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
        }
        result = gpr.compare_chapter(expected, actual)
        self.assertEqual(result["falseNegatives"], 1)
        self.assertEqual(result["missingSectionNumbers"], ["12.020"])
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["precision"], 1.0)

    def test_a_section_the_parser_over_reports_is_a_false_positive_and_lowers_precision(self):
        expected = self.expected_doc([
            {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
        ])
        actual = {
            "12.010": {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
            "12.015": {"sectionNumber": "12.015", "catchline": "Phantom.", "status": "operative"},
        }
        result = gpr.compare_chapter(expected, actual)
        self.assertEqual(result["falsePositives"], 1)
        self.assertEqual(result["unexpectedSectionNumbers"], ["12.015"])
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 1.0)

    def test_a_catchline_mismatch_on_an_otherwise_matched_section_is_recorded(self):
        expected = self.expected_doc([
            {"sectionNumber": "12.010", "catchline": "Correct catchline.", "status": "operative"},
        ])
        actual = {
            "12.010": {"sectionNumber": "12.010", "catchline": "Wrong catchline.", "status": "operative"},
        }
        result = gpr.compare_chapter(expected, actual)
        # The section itself still counts as found -- this is a field
        # disagreement, not a coverage gap.
        self.assertEqual(result["truePositives"], 1)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["catchlineExactMatchRate"], 0.0)
        self.assertEqual(
            result["catchlineMismatches"],
            [{"sectionNumber": "12.010", "expected": "Correct catchline.", "actual": "Wrong catchline."}],
        )

    def test_a_status_mismatch_is_recorded_independently_of_catchline(self):
        expected = self.expected_doc([
            {"sectionNumber": "12.030", "catchline": None, "status": "repealed"},
        ])
        actual = {
            "12.030": {"sectionNumber": "12.030", "catchline": None, "status": "operative"},
        }
        result = gpr.compare_chapter(expected, actual)
        self.assertEqual(result["statusExactMatchRate"], 0.0)
        self.assertEqual(
            result["statusMismatches"],
            [{"sectionNumber": "12.030", "expected": "repealed", "actual": "operative"}],
        )

    def test_renumbered_to_is_only_scored_when_either_side_says_renumbered(self):
        expected = self.expected_doc([
            {"sectionNumber": "12.010", "catchline": "Ordinary.", "status": "operative"},
            {"sectionNumber": "105.117", "catchline": None, "status": "renumbered", "renumberedTo": "91.122"},
        ])
        actual = {
            "12.010": {"sectionNumber": "12.010", "catchline": "Ordinary.", "status": "operative"},
            "105.117": {"sectionNumber": "105.117", "catchline": None, "status": "renumbered", "renumberedTo": "91.122"},
        }
        result = gpr.compare_chapter(expected, actual)
        # Only the renumbered section is a candidate; the ordinary one never
        # touches the renumbered_to rate at all.
        self.assertEqual(result["renumberedToCandidates"], 1)
        self.assertEqual(result["renumberedToExactMatchRate"], 1.0)

    def test_a_wrong_renumbered_to_destination_is_caught(self):
        expected = self.expected_doc([
            {"sectionNumber": "105.117", "catchline": None, "status": "renumbered", "renumberedTo": "91.122"},
        ])
        actual = {
            "105.117": {"sectionNumber": "105.117", "catchline": None, "status": "renumbered", "renumberedTo": "91.999"},
        }
        result = gpr.compare_chapter(expected, actual)
        self.assertEqual(result["renumberedToExactMatchRate"], 0.0)
        self.assertEqual(
            result["renumberedToMismatches"],
            [{"sectionNumber": "105.117", "expected": "91.122", "actual": "91.999"}],
        )

    def test_a_chapter_with_no_expected_sections_at_all_is_not_a_division_by_zero(self):
        # Degenerate but should never crash: an empty review scores perfect
        # precision/recall/rates by definition (no expectations to violate),
        # rather than raising ZeroDivisionError.
        expected = self.expected_doc([])
        result = gpr.compare_chapter(expected, {})
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)
        self.assertEqual(result["catchlineExactMatchRate"], 1.0)
        self.assertEqual(result["renumberedToExactMatchRate"], 1.0)

    def test_aggregate_sums_raw_counts_across_chapters_rather_than_averaging_rates(self):
        # Chapter A: 1/2 sections found (recall 0.5). Chapter B: 2/2 (recall
        # 1.0). A naive average of the two rates would give 0.75; the true
        # pooled recall over all 4 expected sections is 3/4 = 0.75 here too
        # by coincidence, so use uneven chapter sizes to tell them apart.
        chapter_a = gpr.compare_chapter(
            self.expected_doc([
                {"sectionNumber": "12.010", "catchline": "A.", "status": "operative"},
                {"sectionNumber": "12.020", "catchline": "B.", "status": "operative"},
                {"sectionNumber": "12.030", "catchline": "C.", "status": "operative"},
            ]),
            {
                "12.010": {"sectionNumber": "12.010", "catchline": "A.", "status": "operative"},
            },
        )
        chapter_b = gpr.compare_chapter(
            self.expected_doc([
                {"sectionNumber": "105.005", "catchline": "D.", "status": "operative"},
            ]),
            {
                "105.005": {"sectionNumber": "105.005", "catchline": "D.", "status": "operative"},
            },
        )
        overall = gpr.aggregate([chapter_a, chapter_b])
        # Pooled: 2 true positives (1 + 1) over 4 expected (3 + 1) = 0.5,
        # not the simple average of 1/3 and 1/1 (which would be ~0.667).
        self.assertEqual(overall["truePositives"], 2)
        self.assertEqual(overall["falseNegatives"], 2)
        self.assertEqual(overall["recall"], 0.5)


class CliTests(unittest.TestCase):
    def write(self, directory, name, value):
        path = Path(directory) / name
        path.write_text(json.dumps(value))
        return path

    def test_a_clean_run_exits_zero_and_reports_perfect_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            gold_dir.mkdir()
            self.write(gold_dir, "chapter-12-expected-sections.json", {
                "chapterNumber": "12",
                "editionYear": 2025,
                "expectedSections": [
                    {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
                ],
            })
            rows_path = self.write(tmp, "rows.json", {
                "sections": [
                    {
                        "chapterId": "2025-12",
                        "sectionNumber": "12.010",
                        "catchline": "First.",
                        "status": "operative",
                    },
                ],
            })
            report_path = Path(tmp) / "report.json"
            exit_code = gpr.main([
                "--gold-dir", str(gold_dir),
                "--rows", str(rows_path),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["overall"]["precision"], 1.0)
            self.assertEqual(report["overall"]["recall"], 1.0)

    def test_a_missing_section_fails_the_gate_with_a_specific_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            gold_dir.mkdir()
            self.write(gold_dir, "chapter-12-expected-sections.json", {
                "chapterNumber": "12",
                "editionYear": 2025,
                "expectedSections": [
                    {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
                    {"sectionNumber": "12.020", "catchline": "Second.", "status": "operative"},
                ],
            })
            rows_path = self.write(tmp, "rows.json", {
                "sections": [
                    {
                        "chapterId": "2025-12",
                        "sectionNumber": "12.010",
                        "catchline": "First.",
                        "status": "operative",
                    },
                ],
            })
            report_path = Path(tmp) / "report.json"
            exit_code = gpr.main([
                "--gold-dir", str(gold_dir),
                "--rows", str(rows_path),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertFalse(report["valid"])
            self.assertTrue(any("recall" in failure for failure in report["failures"]))

    def test_custom_thresholds_can_tolerate_a_known_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            gold_dir.mkdir()
            self.write(gold_dir, "chapter-12-expected-sections.json", {
                "chapterNumber": "12",
                "editionYear": 2025,
                "expectedSections": [
                    {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
                    {"sectionNumber": "12.020", "catchline": "Second.", "status": "operative"},
                ],
            })
            rows_path = self.write(tmp, "rows.json", {
                "sections": [
                    {
                        "chapterId": "2025-12",
                        "sectionNumber": "12.010",
                        "catchline": "First.",
                        "status": "operative",
                    },
                ],
            })
            thresholds_path = self.write(tmp, "thresholds.json", {"recall": 0.4})
            report_path = Path(tmp) / "report.json"
            exit_code = gpr.main([
                "--gold-dir", str(gold_dir),
                "--rows", str(rows_path),
                "--report", str(report_path),
                "--thresholds", str(thresholds_path),
            ])
            self.assertEqual(exit_code, 0)

    def test_a_chapter_with_no_matching_rows_is_all_false_negatives_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            gold_dir.mkdir()
            self.write(gold_dir, "chapter-12-expected-sections.json", {
                "chapterNumber": "12",
                "editionYear": 2025,
                "expectedSections": [
                    {"sectionNumber": "12.010", "catchline": "First.", "status": "operative"},
                ],
            })
            # rows.json has sections, but none for edition 2025 chapter 12 --
            # e.g. the parser never even reached this chapter.
            rows_path = self.write(tmp, "rows.json", {"sections": []})
            report_path = Path(tmp) / "report.json"
            exit_code = gpr.main([
                "--gold-dir", str(gold_dir),
                "--rows", str(rows_path),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 1)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["overall"]["falseNegatives"], 1)

    def test_no_gold_review_files_found_raises_rather_than_silently_passing(self):
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            gold_dir.mkdir()
            rows_path = self.write(tmp, "rows.json", {"sections": []})
            with self.assertRaisesRegex(ValueError, "no chapter-.*-expected-sections.json"):
                gpr.main([
                    "--gold-dir", str(gold_dir),
                    "--rows", str(rows_path),
                    "--report", str(Path(tmp) / "report.json"),
                ])


if __name__ == "__main__":
    unittest.main()
