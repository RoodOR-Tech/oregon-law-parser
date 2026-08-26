#!/usr/bin/env python3
import argparse
import glob
import json
import sys
from pathlib import Path

QUALITY_TARGETS = {
    "sectionPrecision": 0.999,
    "sectionRecall": 0.995,
    "metadataExactMatch": 1.0,
}


def load(path):
    return json.loads(Path(path).read_text())


def by_id(documents, label):
    result = {}
    for item in documents:
        doc_id = item.get("id")
        if not doc_id:
            raise ValueError(f"{label}: document missing id")
        if doc_id in result:
            raise ValueError(f"{label}: duplicate id {doc_id}")
        result[doc_id] = item
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True)
    parser.add_argument("--hashes", required=True)
    parser.add_argument("--reviews-glob", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    selection = load(args.selection)
    hashes = load(args.hashes)
    review_paths = sorted(glob.glob(args.reviews_glob))
    if not review_paths:
        raise ValueError("no review files matched")

    selected = by_id(selection.get("documents", []), "selection")
    hashed = by_id(hashes.get("documents", []), "hashes")

    reviews = {}
    for path in review_paths:
        review_file = load(path)
        if review_file.get("reviewStatus") != "independently-reviewed":
            raise ValueError(f"{path}: reviewStatus is not independently-reviewed")
        for item in review_file.get("documents", []):
            doc_id = item.get("id")
            if doc_id in reviews:
                raise ValueError(f"reviews: duplicate id {doc_id}")
            reviews[doc_id] = item

    selected_ids = set(selected)
    if len(selected_ids) != 25:
        raise ValueError(f"selection must contain exactly 25 documents, found {len(selected_ids)}")
    if set(hashed) != selected_ids:
        raise ValueError("hash id set does not exactly match frozen selection")
    if set(reviews) != selected_ids:
        missing = sorted(selected_ids - set(reviews))
        extra = sorted(set(reviews) - selected_ids)
        raise ValueError(f"review id set mismatch; missing={missing}, extra={extra}")

    documents = []
    for doc_id in sorted(selected_ids):
        selected_item = selected[doc_id]
        hash_item = hashed[doc_id]
        reviewed = reviews[doc_id]

        if reviewed.get("sourceUrl") != selected_item.get("sourceUrl"):
            raise ValueError(f"{doc_id}: reviewed sourceUrl differs from frozen selection")
        if reviewed.get("sourceSha256") != hash_item.get("sha256"):
            raise ValueError(f"{doc_id}: reviewed sourceSha256 differs from staged source hash")
        if hash_item.get("sourceFormat") not in {"pdf", "html"}:
            raise ValueError(f"{doc_id}: unsupported source format")
        expected = reviewed.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"{doc_id}: missing reviewed expected object")
        for key in ("year", "chapter", "bill", "effectiveDate", "affectedSections"):
            if key not in expected:
                raise ValueError(f"{doc_id}: expected missing {key}")
        if not reviewed.get("reviewBasis") or not reviewed.get("reviewSources"):
            raise ValueError(f"{doc_id}: independent review provenance incomplete")

        ext = ".pdf" if hash_item["sourceFormat"] == "pdf" else ".html"
        documents.append({
            "id": doc_id,
            "fixture": f"validation-fixtures/{doc_id}{ext}",
            "sourceUrl": selected_item["sourceUrl"],
            "sourceSha256": hash_item["sha256"],
            "sourceFormat": hash_item["sourceFormat"],
            "reviewStatus": "independently-reviewed",
            "reviewBasis": reviewed["reviewBasis"],
            "reviewSources": reviewed["reviewSources"],
            "caseTags": selected_item.get("caseTags", []),
            "expected": expected,
        })

    manifest = {
        "schemaVersion": 1,
        "corpusType": "unseen-validation",
        "validationStatus": "expectations-frozen",
        "goldBaselineCommit": selection.get("goldBaselineCommit"),
        "selectionCommit": hashes.get("selectionCommit"),
        "qualityTargets": QUALITY_TARGETS,
        "documents": documents,
    }
    Path(args.output).write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"schemaVersion": 1, "valid": True, "documentCount": len(documents), "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"schemaVersion": 1, "valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        sys.exit(1)
