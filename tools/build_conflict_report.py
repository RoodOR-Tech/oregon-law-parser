#!/usr/bin/env python3
import argparse
import csv
import json
from pathlib import Path


def section_pairs(change_set):
    pairs = set()
    for section in change_set.get("amended", []):
        pairs.add(("amended", section))
    for section in change_set.get("repealed", []):
        pairs.add(("repealed", section))
    return pairs


def load_lc_rows(path):
    if not path:
        return []
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def matching_lc(rows, year, chapter):
    matches = []
    for row in rows:
        try:
            row_year = int(row["source_year"])
            row_chapter = int(row["oregon_laws_chapter"])
        except (KeyError, TypeError, ValueError):
            continue
        if row_year == year and row_chapter == chapter:
            matches.append(row)
    return matches


def evidence_for_pairs(actual, pairs):
    wanted = set(pairs)
    evidence = []
    for item in actual.get("validation", {}).get("sectionEvidence", []):
        raw_action = str(item.get("evidenceAction", "")).lower()
        action = {
            "amend": "amended",
            "amended": "amended",
            "repeal": "repealed",
            "repealed": "repealed",
        }.get(raw_action, raw_action)
        pair = (action, item.get("evidenceSection"))
        if pair in wanted:
            evidence.append(item)
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--lc-csv")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    quality = json.loads(Path(args.quality_report).read_text())
    results_dir = Path(args.results_dir)
    lc_rows = load_lc_rows(args.lc_csv)
    by_id = {item["id"]: item for item in manifest["documents"]}

    cases = []
    for doc_quality in quality.get("documents", []):
        doc_id = doc_quality["id"]
        manifest_item = by_id.get(doc_id)
        result_path = results_dir / f"{doc_id}.json"
        if not manifest_item or not result_path.exists():
            continue

        actual = json.loads(result_path.read_text())
        expected = manifest_item["expected"]
        expected_pairs = section_pairs(expected["affectedSections"])
        actual_pairs = section_pairs(actual.get("affectedSections", {}))
        false_positives = sorted(actual_pairs - expected_pairs)
        false_negatives = sorted(expected_pairs - actual_pairs)
        metadata_mismatch = not doc_quality.get("metadataExactMatch", False)
        parser_status = actual.get("validation", {}).get("validationStatus")
        needs_review = bool(
            false_positives
            or false_negatives
            or metadata_mismatch
            or parser_status in {"Conflict", "Incomplete"}
        )
        if not needs_review:
            continue

        mismatch_pairs = false_positives + false_negatives
        cases.append({
            "id": doc_id,
            "sourceUrl": manifest_item.get("sourceUrl"),
            "reviewBasis": manifest_item.get("reviewBasis"),
            "parserValidationStatus": parser_status,
            "expected": expected,
            "actual": {
                "year": actual.get("year"),
                "chapter": actual.get("chapter"),
                "bill": actual.get("bill"),
                "effectiveDate": actual.get("effectiveDate"),
                "affectedSections": actual.get("affectedSections", {}),
            },
            "falsePositives": [list(pair) for pair in false_positives],
            "falseNegatives": [list(pair) for pair in false_negatives],
            "metadataExactMatch": not metadata_mismatch,
            "parserEvidence": evidence_for_pairs(actual, mismatch_pairs),
            "allParserEvidence": actual.get("validation", {}).get("sectionEvidence", []),
            "legislativeCounselEvidence": matching_lc(
                lc_rows, expected["year"], expected["chapter"]
            ),
        })

    report = {
        "schemaVersion": 1,
        "reviewCaseCount": len(cases),
        "qualityGatePassed": quality.get("gatePassed", False),
        "releaseCertifying": quality.get("releaseCertifying", False),
        "cases": cases,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
