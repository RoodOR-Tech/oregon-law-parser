"""Verify reviewed ORS action references against operative parser evidence.

This is scoped verification of reviewed references, not whole-document recall
certification, effective-date analysis, or application of amendments.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from resolve_general_notices import review_index


def verify_reference(ref, year, payload, acquisition):
    """Return a classification and supporting evidence for one reviewed row."""
    if not isinstance(payload, dict):
        return "invalid-result", []
    if payload.get("errors"):
        return "parser-error", []
    if (type(payload.get("year")) is not int or payload["year"] != year
            or type(payload.get("chapter")) is not int
            or payload["chapter"] != ref["sessionLawChapter"]):
        return "identity-mismatch", []
    provenance = payload.get("provenance")
    if (not isinstance(acquisition, dict) or acquisition.get("ok") is not True
            or not isinstance(provenance, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(acquisition.get("sha256", "")))
            or not acquisition.get("sourceUrl")
            or provenance.get("sourceSha256") != acquisition["sha256"]
            or provenance.get("sourceUrl") != acquisition["sourceUrl"]):
        return "provenance-mismatch", []
    bill = payload.get("bill", {})
    if not isinstance(bill, dict) or f"{bill.get('billType')} {bill.get('billNumber')}" != ref.get("measure"):
        return "measure-mismatch", []
    changes = payload.get("affectedSections")
    validation = payload.get("validation")
    if (not isinstance(changes, dict) or not isinstance(validation, dict)
            or any(not isinstance(changes.get(k), list) or not all(isinstance(x, str) for x in changes[k])
                   for k in ("amended", "repealed"))
            or not isinstance(validation.get("sectionEvidence"), list)
            or any(not isinstance(e, dict) for e in validation["sectionEvidence"])):
        return "invalid-result", []
    expected_action = "AmendmentAction" if ref["action"] == "A" else "RepealAction"
    expected_bucket = "amended" if ref["action"] == "A" else "repealed"
    opposite_bucket = "repealed" if ref["action"] == "A" else "amended"
    evidence = [e for e in validation["sectionEvidence"]
                if e.get("evidenceSectionNumber") == ref["orsSection"]]
    operative = [e for e in evidence if e.get("evidenceSource") == "OperativeBodyEvidence"
                 and e.get("evidenceSectionClause") == ref["sessionLawSection"]]
    if any(e.get("evidenceAction") != expected_action for e in operative):
        return "conflicting-action", evidence
    if ref["orsSection"] not in changes[expected_bucket]:
        return ("conflicting-action" if ref["orsSection"] in changes[opposite_bucket]
                else "missing-affected-section"), evidence
    if not operative:
        return "missing-operative-evidence", evidence
    if not all(isinstance(e.get("evidenceText"), str) and e["evidenceText"].strip() for e in operative):
        return "invalid-result", evidence
    return "exact-match", operative


def verify(reviews, results_dir, acquisition_report):
    acquired = {}
    for doc in acquisition_report.get("documents", []):
        if doc.get("id") in acquired:
            raise ValueError("duplicate acquisition identity")
        acquired[doc.get("id")] = doc
    rows, seen = [], set()
    for review in reviews:
        review_index(review)
        year = review["sessionYear"]
        for ref in review["references"]:
            key = (year, ref["sessionLawChapter"], ref["sessionLawSection"], ref["orsSection"], ref["action"])
            if key in seen:
                raise ValueError("duplicate reviewed reference across reviews")
            seen.add(key)
            doc_id = f"{year}orlaw{ref['sessionLawChapter']:04d}"
            path = Path(results_dir) / (doc_id + ".json")
            payload = None
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                status, evidence = "missing-result", []
            except (json.JSONDecodeError, UnicodeError):
                status, evidence = "invalid-result", []
            else:
                status, evidence = verify_reference(ref, year, payload, acquired.get(doc_id))
            rows.append({**ref, "sessionYear": year, "documentId": doc_id,
                         "status": status, "evidence": evidence,
                         "reviewSource": review["source"],
                         "parserProvenance": payload.get("provenance") if isinstance(payload, dict) else None,
                         "documentValidationStatus": (payload.get("validation") or {}).get("validationStatus")
                         if isinstance(payload, dict) and isinstance(payload.get("validation"), dict) else None})
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    return {"schemaVersion": 1, "scope": __doc__.strip(),
            "referenceCount": len(rows), "exactMatchCount": counts.get("exact-match", 0),
            "statusCounts": counts, "gatePassed": bool(rows) and counts.get("exact-match", 0) == len(rows),
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="append", required=True)
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--acquisition-report", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    reviews = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.review]
    report = verify(reviews, args.results_dir, json.loads(Path(args.acquisition_report).read_text(encoding="utf-8")))
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    for row in report["rows"]:
        if row["status"] != "exact-match":
            print(json.dumps(row))
    return 0 if report["gatePassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
