#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text())


def fail(message):
    raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True)
    parser.add_argument("--hashes", required=True)
    parser.add_argument("--reviews", nargs="+", required=True)
    parser.add_argument("--quality-targets-from", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    selection = load(args.selection)
    hashes = load(args.hashes)
    quality_source = load(args.quality_targets_from)

    selected = selection.get("documents", [])
    if len(selected) != 25:
        fail(f"expected frozen selection of 25 documents, got {len(selected)}")
    selection_by_id = {item["id"]: item for item in selected}
    if len(selection_by_id) != len(selected):
        fail("duplicate IDs in frozen selection")

    hash_docs = hashes.get("documents", [])
    hash_by_id = {item["id"]: item for item in hash_docs}
    if not hashes.get("valid") or set(hash_by_id) != set(selection_by_id):
        fail("source-hash registry does not exactly cover frozen selection")

    reviewed = {}
    for review_path in args.reviews:
        review = load(review_path)
        if review.get("reviewStatus") != "independently-reviewed":
            fail(f"{review_path}: reviewStatus is not independently-reviewed")
        for item in review.get("documents", []):
            doc_id = item["id"]
            if doc_id in reviewed:
                fail(f"duplicate reviewed ID: {doc_id}")
            reviewed[doc_id] = item

    if set(reviewed) != set(selection_by_id):
        missing = sorted(set(selection_by_id) - set(reviewed))
        extra = sorted(set(reviewed) - set(selection_by_id))
        fail(f"review coverage mismatch; missing={missing}, extra={extra}")

    documents = []
    for item in selected:
        doc_id = item["id"]
        review = reviewed[doc_id]
        hash_item = hash_by_id[doc_id]
        if review.get("sourceUrl") != item.get("sourceUrl"):
            fail(f"{doc_id}: reviewed URL differs from frozen selection")
        if review.get("sourceSha256") != hash_item.get("sha256"):
            fail(f"{doc_id}: reviewed hash differs from pre-evaluation hash registry")
        fmt = hash_item.get("sourceFormat")
        if fmt not in {"html", "pdf"}:
            fail(f"{doc_id}: unsupported source format {fmt!r}")
        documents.append({
            "id": doc_id,
            "fixture": f"validation-fixtures/{doc_id}.{fmt}",
            "sourceUrl": item["sourceUrl"],
            "sourceSha256": hash_item["sha256"],
            "caseTags": item.get("caseTags", []),
            "reviewStatus": "independently-reviewed",
            "reviewBasis": review.get("reviewBasis"),
            "reviewSources": review.get("reviewSources", []),
            "expected": review["expected"],
        })

    output = {
        "schemaVersion": 1,
        "corpusType": "unseen-validation",
        "selectionStatus": "frozen-reviewed-before-parser-evaluation",
        "selectionCommit": hashes.get("selectionCommit"),
        "sourceHashStagingRunId": hashes.get("stagingRunId"),
        "sourceHashArtifactDigest": hashes.get("artifactDigest"),
        "qualityTargets": quality_source["qualityTargets"],
        "documents": documents,
    }
    Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"valid": True, "documentCount": len(documents), "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"validation manifest error: {exc}", file=sys.stderr)
        sys.exit(1)
