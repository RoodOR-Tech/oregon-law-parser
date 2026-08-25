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
    failures = []
    documents = []

    for item in manifest["documents"]:
        result_path = results_dir / f'{item["id"]}.json'
        if not result_path.exists():
            failures.append(f'{item["id"]}: missing parser result {result_path}')
            continue

        actual = json.loads(result_path.read_text())
        expected = item["expected"]

        expected_pairs = section_pairs(expected["affectedSections"])
        actual_pairs = section_pairs(actual.get("affectedSections", {}))
        doc_tp = len(expected_pairs & actual_pairs)
        doc_fp = len(actual_pairs - expected_pairs)
        doc_fn = len(expected_pairs - actual_pairs)
        tp += doc_tp
        fp += doc_fp
        fn += doc_fn

        metadata_matches = (
            actual.get("year") == expected["year"]
            and actual.get("chapter") == expected["chapter"]
            and actual.get("bill") == expected["bill"]
            and actual.get("effectiveDate") == expected["effectiveDate"]
        )
        metadata_correct += int(metadata_matches)

        documents.append({
            "id": item["id"],
            "truePositives": doc_tp,
            "falsePositives": sorted([list(x) for x in actual_pairs - expected_pairs]),
            "falseNegatives": sorted([list(x) for x in expected_pairs - actual_pairs]),
            "metadataExactMatch": metadata_matches,
        })

    total_docs = len(manifest["documents"])
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    metadata_rate = safe_ratio(metadata_correct, total_docs)
    targets = manifest["qualityTargets"]

    gate_passed = (
        not failures
        and precision >= targets["sectionPrecision"]
        and recall >= targets["sectionRecall"]
        and metadata_rate >= targets["metadataExactMatch"]
    )

    cert_min = manifest.get("releaseCertificationMinimumDocuments", 50)
    report = {
        "schemaVersion": 1,
        "goldDocuments": total_docs,
        "releaseCertificationMinimumDocuments": cert_min,
        "releaseCertifying": gate_passed and total_docs >= cert_min,
        "gatePassed": gate_passed,
        "metrics": {
            "truePositives": tp,
            "falsePositives": fp,
            "falseNegatives": fn,
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

    if not gate_passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
