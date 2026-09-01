#!/usr/bin/env python3
"""Validate and freeze source provenance for the ORS gold candidate selection.

This tool consumes only the candidate selection plus the acquisition report.
It never reads parser output. Its job is to prove that the exact authoritative
bytes used for later independent review were fixed before parser evaluation.
"""
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
    parser.add_argument("--acquisition", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    selection = load(args.selection)
    acquisition = load(args.acquisition)

    if selection.get("selectionStatus") != "frozen-before-parser-evaluation":
        fail("selection is not frozen before parser evaluation")
    selected = selection.get("chapters", [])
    if not selected:
        fail("selection contains no chapters")

    selected_by_number = {item.get("chapterNumber"): item for item in selected}
    if None in selected_by_number or len(selected_by_number) != len(selected):
        fail("selection has malformed or duplicate chapter numbers")

    if not acquisition.get("valid"):
        fail("acquisition report is not valid")
    acquired = acquisition.get("chapters", [])
    acquired_by_number = {item.get("chapterNumber"): item for item in acquired}
    if set(acquired_by_number) != set(selected_by_number):
        fail("acquisition coverage does not exactly match frozen selection")

    documents = []
    for number, selected_item in selected_by_number.items():
        acquired_item = acquired_by_number[number]
        if not acquired_item.get("ok"):
            fail(f"chapter {number}: source was not acquired")
        if acquired_item.get("sourceUrl") != selected_item.get("sourceUrl"):
            fail(f"chapter {number}: acquired URL differs from frozen selection")
        digest = acquired_item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            fail(f"chapter {number}: malformed SHA-256")
        documents.append({
            "chapterNumber": number,
            "sourceUrl": acquired_item["sourceUrl"],
            "sourceFormat": acquired_item.get("sourceFormat"),
            "sha256": digest,
            "bytes": acquired_item.get("bytes"),
            "httpStatus": acquired_item.get("httpStatus"),
            "retrievedAt": acquired_item.get("retrievedAt"),
        })

    output = {
        "schemaVersion": 1,
        "corpusType": "ors-gold-source-registry",
        "selectionStatus": selection["selectionStatus"],
        "editionYear": selection.get("editionYear"),
        "valid": True,
        "documentCount": len(documents),
        "documents": documents,
    }
    Path(args.output).write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({"valid": True, "documentCount": len(documents), "output": args.output}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ORS gold source staging error: {exc}", file=sys.stderr)
        sys.exit(1)
