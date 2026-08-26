#!/usr/bin/env python3
import argparse
import collections
import json
import re
import sys
from pathlib import Path

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VALIDATION_STATUSES = {"Verified", "ParsedUnverified", "Conflict", "Incomplete"}
VALID_BILL_TYPES = {"HB", "SB", "BallotMeasure"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--first-chapter", type=int, default=1)
    parser.add_argument("--last-chapter", type=int, required=True)
    parser.add_argument("--acquisition-report", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    acquisition = json.loads(Path(args.acquisition_report).read_text())
    results_dir = Path(args.results_dir)
    acquired = {item["chapter"]: item for item in acquisition.get("documents", []) if item.get("ok")}

    validation_counts = collections.Counter()
    parser_failures = []
    metadata_mismatches = []
    provenance_mismatches = []
    malformed_results = []
    conflicts = []
    parsed_unverified = []
    incomplete = []
    zero_change = []
    documents = []
    total_amended = 0
    total_repealed = 0

    for chapter in range(args.first_chapter, args.last_chapter + 1):
        doc_id = f"{args.year}orlaw{chapter:04d}"
        expected_source = acquired.get(chapter)
        result_path = results_dir / f"{doc_id}.json"
        doc_summary = {"id": doc_id, "chapter": chapter}

        if expected_source is None:
            parser_failures.append({"id": doc_id, "reason": "source was not acquired"})
            doc_summary["status"] = "source-acquisition-failed"
            documents.append(doc_summary)
            continue
        if not result_path.exists():
            parser_failures.append({"id": doc_id, "reason": "parser result missing"})
            doc_summary["status"] = "missing-result"
            documents.append(doc_summary)
            continue
        try:
            actual = json.loads(result_path.read_text())
        except Exception as exc:
            malformed_results.append({"id": doc_id, "reason": str(exc)})
            doc_summary["status"] = "malformed-result"
            documents.append(doc_summary)
            continue

        if actual.get("errors"):
            parser_failures.append({"id": doc_id, "errors": actual["errors"]})
            doc_summary["status"] = "parser-failure"
            documents.append(doc_summary)
            continue

        mismatches = []
        if actual.get("year") != args.year:
            mismatches.append({"field": "year", "expected": args.year, "actual": actual.get("year")})
        if actual.get("chapter") != chapter:
            mismatches.append({"field": "chapter", "expected": chapter, "actual": actual.get("chapter")})
        if not isinstance(actual.get("bill"), dict) or actual["bill"].get("billType") not in VALID_BILL_TYPES or not isinstance(actual["bill"].get("billNumber"), int):
            mismatches.append({"field": "bill", "expected": "HB/SB/BallotMeasure with integer billNumber", "actual": actual.get("bill")})
        if not isinstance(actual.get("effectiveDate"), str) or not actual.get("effectiveDate"):
            mismatches.append({"field": "effectiveDate", "expected": "non-empty date", "actual": actual.get("effectiveDate")})
        if mismatches:
            metadata_mismatches.append({"id": doc_id, "mismatches": mismatches})

        provenance = actual.get("provenance") or {}
        prov_errors = []
        digest = provenance.get("sourceSha256")
        if digest != expected_source.get("sha256") or not isinstance(digest, str) or not SHA256_RE.match(digest):
            prov_errors.append({"field": "sourceSha256", "expected": expected_source.get("sha256"), "actual": digest})
        if provenance.get("sourceUrl") != expected_source.get("sourceUrl"):
            prov_errors.append({"field": "sourceUrl", "expected": expected_source.get("sourceUrl"), "actual": provenance.get("sourceUrl")})
        if not provenance.get("sourcePath"):
            prov_errors.append({"field": "sourcePath", "expected": "non-empty", "actual": provenance.get("sourcePath")})
        if prov_errors:
            provenance_mismatches.append({"id": doc_id, "mismatches": prov_errors})

        validation = actual.get("validation") or {}
        status = validation.get("validationStatus")
        if status not in VALIDATION_STATUSES:
            malformed_results.append({"id": doc_id, "reason": f"unknown validation status {status!r}"})
            status = "Unknown"
        validation_counts[status] += 1

        changes = actual.get("affectedSections") or {}
        amended = changes.get("amended") if isinstance(changes.get("amended"), list) else []
        repealed = changes.get("repealed") if isinstance(changes.get("repealed"), list) else []
        total_amended += len(amended)
        total_repealed += len(repealed)
        if not amended and not repealed:
            zero_change.append(doc_id)
        if status == "Conflict":
            conflicts.append(doc_id)
        elif status == "ParsedUnverified":
            parsed_unverified.append(doc_id)
        elif status == "Incomplete":
            incomplete.append(doc_id)

        doc_summary.update({
            "status": "parsed",
            "bill": actual.get("bill"),
            "effectiveDate": actual.get("effectiveDate"),
            "validationStatus": status,
            "amendedCount": len(amended),
            "repealedCount": len(repealed),
        })
        documents.append(doc_summary)

    expected_documents = args.last_chapter - args.first_chapter + 1
    parsed_documents = sum(1 for item in documents if item.get("status") == "parsed")
    hard_failures = len(parser_failures) + len(malformed_results) + len(metadata_mismatches) + len(provenance_mismatches)
    gate_passed = (
        acquisition.get("valid") is True
        and acquisition.get("expectedDocuments") == expected_documents
        and acquisition.get("acquiredDocuments") == expected_documents
        and parsed_documents == expected_documents
        and hard_failures == 0
    )

    report = {
        "schemaVersion": 1,
        "corpusType": "operational-full-session",
        "sessionYear": args.year,
        "chapterRange": {"first": args.first_chapter, "last": args.last_chapter},
        "expectedDocuments": expected_documents,
        "acquiredDocuments": acquisition.get("acquiredDocuments", 0),
        "parsedDocuments": parsed_documents,
        "operationalGatePassed": gate_passed,
        "operationCounts": {
            "amended": total_amended,
            "repealed": total_repealed,
            "total": total_amended + total_repealed,
        },
        "validationStatusCounts": dict(sorted(validation_counts.items())),
        "reviewQueues": {
            "conflict": conflicts,
            "parsedUnverified": parsed_unverified,
            "incomplete": incomplete,
            "zeroChange": zero_change,
        },
        "failures": {
            "parser": parser_failures,
            "malformedResults": malformed_results,
            "metadataMismatch": metadata_mismatches,
            "provenanceMismatch": provenance_mismatches,
        },
        "documents": documents,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "operationalGatePassed": gate_passed,
        "expectedDocuments": expected_documents,
        "acquiredDocuments": report["acquiredDocuments"],
        "parsedDocuments": parsed_documents,
        "operationCounts": report["operationCounts"],
        "validationStatusCounts": report["validationStatusCounts"],
        "reviewQueueCounts": {key: len(value) for key, value in report["reviewQueues"].items()},
        "hardFailureCount": hard_failures,
    }, indent=2))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    sys.exit(main())
