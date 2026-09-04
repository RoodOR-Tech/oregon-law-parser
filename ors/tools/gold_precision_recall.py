#!/usr/bin/env python3
"""Measure parse_ors_chapter.py against the independently reviewed gold chapters.

Increment 5's quality gate. Each `ors/gold/reviews/chapter-*-expected-sections.json`
file is an independent reviewer's own reading of one frozen chapter's source text --
established without ever running the parser first (see each file's own `reviewBasis`
and `methodology.expectedRowsEstablishedFromParserOutput: false`). This tool compares
that ground truth against the parser's real output on the same frozen bytes.

Two things are measured, matching ROADMAP.md's own increment 5 description:

  - Section coverage: precision and recall over (chapter, section_number) pairs.
    A section the parser emits that the review does not expect is a false positive
    (over-counting, e.g. a table-of-contents entry mistaken for a body section); a
    section the review expects that the parser does not emit is a false negative
    (under-counting, e.g. chapter 105's quoted-catchline sections before that bug
    was fixed).
  - Field agreement: among sections found in both (true positives), the fraction
    with an exact catchline match, an exact status match, and -- for sections
    either side calls renumbered -- an exact renumbered_to match.

Thresholds are read from --thresholds rather than hardcoded, because ROADMAP.md is
explicit that they are set only after a first real measurement (all five gold
chapters currently score a perfect 1.0 on every metric); baking in "close enough"
numbers up front would flatter the parser instead of describing it.
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_THRESHOLDS = {
    "precision": 1.0,
    "recall": 1.0,
    "catchlineExactMatchRate": 1.0,
    "statusExactMatchRate": 1.0,
    "renumberedToExactMatchRate": 1.0,
}


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_chapter(expected_doc, actual_sections_by_number):
    """Compare one gold review against the parser's actual sections for that chapter.

    `actual_sections_by_number` is already scoped to this chapter (and edition) by
    the caller, so a section number appearing here unambiguously belongs to it.
    """
    expected_by_number = {
        row["sectionNumber"]: row for row in expected_doc["expectedSections"]
    }
    expected_numbers = set(expected_by_number)
    actual_numbers = set(actual_sections_by_number)

    true_positive_numbers = expected_numbers & actual_numbers
    false_negative_numbers = expected_numbers - actual_numbers
    false_positive_numbers = actual_numbers - expected_numbers

    true_positives = len(true_positive_numbers)
    false_negatives = len(false_negative_numbers)
    false_positives = len(false_positive_numbers)

    precision = (
        true_positives / (true_positives + false_positives)
        if (true_positives + false_positives) > 0
        else 1.0
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else 1.0
    )

    catchline_matches = 0
    status_matches = 0
    renumbered_to_candidates = 0
    renumbered_to_matches = 0
    catchline_mismatches = []
    status_mismatches = []
    renumbered_to_mismatches = []

    for number in sorted(true_positive_numbers):
        expected_row = expected_by_number[number]
        actual_row = actual_sections_by_number[number]

        if expected_row.get("catchline") == actual_row.get("catchline"):
            catchline_matches += 1
        else:
            catchline_mismatches.append({
                "sectionNumber": number,
                "expected": expected_row.get("catchline"),
                "actual": actual_row.get("catchline"),
            })

        if expected_row.get("status") == actual_row.get("status"):
            status_matches += 1
        else:
            status_mismatches.append({
                "sectionNumber": number,
                "expected": expected_row.get("status"),
                "actual": actual_row.get("status"),
            })

        expects_renumbered = expected_row.get("status") == "renumbered"
        actual_is_renumbered = actual_row.get("status") == "renumbered"
        if expects_renumbered or actual_is_renumbered:
            renumbered_to_candidates += 1
            if expected_row.get("renumberedTo") == actual_row.get("renumberedTo"):
                renumbered_to_matches += 1
            else:
                renumbered_to_mismatches.append({
                    "sectionNumber": number,
                    "expected": expected_row.get("renumberedTo"),
                    "actual": actual_row.get("renumberedTo"),
                })

    def rate(numerator, denominator):
        return numerator / denominator if denominator > 0 else 1.0

    return {
        "chapterNumber": expected_doc["chapterNumber"],
        "expectedSectionCount": len(expected_numbers),
        "actualSectionCount": len(actual_numbers),
        "truePositives": true_positives,
        "falseNegatives": false_negatives,
        "falsePositives": false_positives,
        "missingSectionNumbers": sorted(false_negative_numbers),
        "unexpectedSectionNumbers": sorted(false_positive_numbers),
        "precision": precision,
        "recall": recall,
        "catchlineMatches": catchline_matches,
        "statusMatches": status_matches,
        "renumberedToCandidates": renumbered_to_candidates,
        "renumberedToMatches": renumbered_to_matches,
        "catchlineExactMatchRate": rate(catchline_matches, true_positives),
        "statusExactMatchRate": rate(status_matches, true_positives),
        "renumberedToExactMatchRate": rate(renumbered_to_matches, renumbered_to_candidates),
        "catchlineMismatches": catchline_mismatches,
        "statusMismatches": status_mismatches,
        "renumberedToMismatches": renumbered_to_mismatches,
    }


def aggregate(per_chapter):
    total_tp = sum(c["truePositives"] for c in per_chapter)
    total_fn = sum(c["falseNegatives"] for c in per_chapter)
    total_fp = sum(c["falsePositives"] for c in per_chapter)
    total_catchline_matches = sum(c["catchlineMatches"] for c in per_chapter)
    total_status_matches = sum(c["statusMatches"] for c in per_chapter)
    total_renumbered_candidates = sum(c["renumberedToCandidates"] for c in per_chapter)
    total_renumbered_matches = sum(c["renumberedToMatches"] for c in per_chapter)

    def rate(numerator, denominator):
        return numerator / denominator if denominator > 0 else 1.0

    precision = rate(total_tp, total_tp + total_fp)
    recall = rate(total_tp, total_tp + total_fn)

    return {
        "chapterCount": len(per_chapter),
        "truePositives": total_tp,
        "falseNegatives": total_fn,
        "falsePositives": total_fp,
        "precision": precision,
        "recall": recall,
        "catchlineExactMatchRate": rate(total_catchline_matches, total_tp),
        "statusExactMatchRate": rate(total_status_matches, total_tp),
        "renumberedToExactMatchRate": rate(total_renumbered_matches, total_renumbered_candidates),
    }


def sections_by_chapter(rows):
    """Group parser rows by chapterId, keyed by sectionNumber within each chapter."""
    by_chapter = {}
    for section in rows.get("sections", []):
        chapter_id = section["chapterId"]
        by_chapter.setdefault(chapter_id, {})[section["sectionNumber"]] = section
    return by_chapter


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold-dir", required=True,
        help="directory containing ors/gold/reviews/chapter-*-expected-sections.json files",
    )
    parser.add_argument("--rows", required=True, help="parse_ors_chapter.py --rows output")
    parser.add_argument("--report", required=True, help="where to write the comparison report")
    parser.add_argument("--thresholds", help="JSON file overriding DEFAULT_THRESHOLDS")
    args = parser.parse_args(argv)

    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.thresholds:
        thresholds.update(load_json(args.thresholds))

    rows = load_json(args.rows)

    gold_dir = Path(args.gold_dir)
    expected_docs = sorted(
        (load_json(path) for path in gold_dir.glob("chapter-*-expected-sections.json")),
        key=lambda doc: doc["chapterNumber"],
    )
    if not expected_docs:
        raise ValueError(f"no chapter-*-expected-sections.json files found in {gold_dir}")

    actual_by_chapter = sections_by_chapter(rows)
    per_chapter = []
    for expected_doc in expected_docs:
        chapter_id = f"{expected_doc['editionYear']}-{expected_doc['chapterNumber']}"
        actual_sections = actual_by_chapter.get(chapter_id, {})
        per_chapter.append(compare_chapter(expected_doc, actual_sections))

    overall = aggregate(per_chapter)

    failures = []
    for metric, minimum in thresholds.items():
        if overall.get(metric, 1.0) < minimum:
            failures.append(
                f"{metric} = {overall[metric]:.6f} is below required minimum {minimum}"
            )

    report = {
        "schemaVersion": 1,
        "corpusType": "ors-gold-precision-recall-report",
        "thresholds": thresholds,
        "overall": overall,
        "perChapter": per_chapter,
        "valid": not failures,
        "failures": failures,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "overall": overall, "failures": failures}, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ORS gold precision/recall error: {exc}", file=sys.stderr)
        sys.exit(1)
