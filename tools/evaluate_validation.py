#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def section_pairs(change_set):
    pairs = set()
    for section in change_set.get("amended", []):
        pairs.add(("amended", section))
    for section in change_set.get("repealed", []):
        pairs.add(("repealed", section))
    return pairs


def safe_ratio(num, den):
    return 1.0 if den == 0 else num / den


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    results_dir = Path(args.results_dir)

    tp = fp = fn = 0
    metadata_correct = 0
    parser_failure_count = 0
    failures = []
    documents = []

    for item in manifest["documents"]:
        result_path = results_dir / f'{item["id"]}.json'
        expected = item["expected"]
        expected_pairs = section_pairs(expected["affectedSections"])

        if not result_path.exists():
            parser_failure_count += 1
            failures.append(f'{item["id"]}: missing parser result {result_path}')
            fn += len(expected_pairs)
            documents.append({
                "id": item["id"], "parserFailed": True,
                "parserErrors": [{"message": "missing parser result"}],
                "truePositives": 0, "falsePositives": [],
                "falseNegatives": sorted([list(x) for x in expected_pairs]),
                "metadataExactMatch": False,
            })
            continue

        try:
            actual = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            parser_failure_count += 1
            failures.append(f'{item["id"]}: unreadable parser result: {exc}')
            fn += len(expected_pairs)
            documents.append({
                "id": item["id"], "parserFailed": True,
                "parserErrors": [{"message": str(exc)}],
                "truePositives": 0, "falsePositives": [],
                "falseNegatives": sorted([list(x) for x in expected_pairs]),
                "metadataExactMatch": False,
            })
            continue

        parser_errors = actual.get("errors", [])
        if parser_errors:
            parser_failure_count += 1
            failures.append(f'{item["id"]}: parser returned structured failure: {json.dumps(parser_errors, sort_keys=True)}')
            fn += len(expected_pairs)
            documents.append({
                "id": item["id"], "parserFailed": True,
                "parserErrors": parser_errors,
                "truePositives": 0, "falsePositives": [],
                "falseNegatives": sorted([list(x) for x in expected_pairs]),
                "metadataExactMatch": False,
            })
            continue

        actual_pairs = section_pairs(actual.get("affectedSections", {}))
        doc_tp = len(expected_pairs & actual_pairs)
        doc_fp_pairs = actual_pairs - expected_pairs
        doc_fn_pairs = expected_pairs - actual_pairs
        tp += doc_tp
        fp += len(doc_fp_pairs)
        fn += len(doc_fn_pairs)

        metadata_matches = (
            actual.get("year") == expected["year"]
            and actual.get("chapter") == expected["chapter"]
            and actual.get("bill") == expected["bill"]
            and actual.get("effectiveDate") == expected["effectiveDate"]
        )
        metadata_correct += int(metadata_matches)

        documents.append({
            "id": item["id"],
            "parserFailed": False,
            "parserErrors": [],
            "truePositives": doc_tp,
            "falsePositives": sorted([list(x) for x in doc_fp_pairs]),
            "falseNegatives": sorted([list(x) for x in doc_fn_pairs]),
            "metadataExactMatch": metadata_matches,
            "validationStatus": actual.get("validation", {}).get("validationStatus"),
        })

    total_docs = len(manifest["documents"])
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    metadata_rate = safe_ratio(metadata_correct, total_docs)
    targets = manifest["qualityTargets"]
    meets_targets = (
        parser_failure_count == 0
        and precision >= targets["sectionPrecision"]
        and recall >= targets["sectionRecall"]
        and metadata_rate >= targets["metadataExactMatch"]
    )

    report = {
        "schemaVersion": 1,
        "corpusType": "unseen-validation",
        "validationDocuments": total_docs,
        "meetsTargets": meets_targets,
        "metrics": {
            "truePositives": tp,
            "falsePositives": fp,
            "falseNegatives": fn,
            "parserFailures": parser_failure_count,
            "sectionPrecision": precision,
            "sectionRecall": recall,
            "metadataExactMatch": metadata_rate,
        },
        "targets": targets,
        "failures": failures,
        "documents": documents,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if meets_targets else 1


if __name__ == "__main__":
    sys.exit(main())
