#!/usr/bin/env python3
"""Validate independently reviewed ORS gold expectations without running parser code."""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ALLOWED_STATUS = {"operative", "repealed", "renumbered", "reserved", "note_only"}
SECTION_RE = re.compile(r"^\d{1,3}[A-Z]?\.\d+[A-Z]?$", re.IGNORECASE)


def load(path):
    return json.loads(Path(path).read_text())


def validate_review(review, provenance):
    errors = []
    chapter = review.get("chapterNumber")
    source_by_chapter = {item["chapterNumber"]: item for item in provenance.get("documents", [])}
    source = source_by_chapter.get(chapter)
    if review.get("reviewStatus") != "independently-reviewed-before-parser-evaluation":
        errors.append("reviewStatus is not frozen independent review")
    method = review.get("reviewMethod", {})
    if method.get("parserOutputConsulted") is not False:
        errors.append("parser output must not be consulted before expectation freeze")
    if method.get("developmentSampleOutputConsulted") is not False:
        errors.append("development-sample parser output must not be consulted")
    if source is None:
        errors.append(f"chapter {chapter!r} not present in staged source provenance")
    else:
        for review_key, source_key in (("sourceUrl", "sourceUrl"), ("sourceSha256", "sha256"), ("sourceBytes", "bytes")):
            if review.get(review_key) != source.get(source_key):
                errors.append(f"{review_key} differs from pre-evaluation source provenance")

    expected = review.get("expected", {})
    sections = expected.get("sections")
    if not isinstance(sections, list) or not sections:
        errors.append("expected.sections must be a nonempty list")
        sections = []
    numbers = []
    status_counts = Counter()
    for index, row in enumerate(sections):
        number = row.get("sectionNumber")
        status = row.get("status")
        catchline = row.get("catchline")
        if not isinstance(number, str) or not SECTION_RE.fullmatch(number):
            errors.append(f"row {index}: malformed sectionNumber {number!r}")
        else:
            numbers.append(number)
            if not number.startswith(f"{chapter}."):
                errors.append(f"row {index}: section {number} is outside chapter {chapter}")
        if status not in ALLOWED_STATUS:
            errors.append(f"row {index}: unsupported status {status!r}")
        else:
            status_counts[status] += 1
        if status == "operative" and (not isinstance(catchline, str) or not catchline.strip()):
            errors.append(f"row {index}: operative section needs a catchline")
        if status != "operative" and catchline is not None and not isinstance(catchline, str):
            errors.append(f"row {index}: malformed catchline")
    if len(numbers) != len(set(numbers)):
        errors.append("duplicate section numbers")
    if expected.get("sectionCount") != len(sections):
        errors.append("sectionCount does not match expected.sections")
    declared_counts = expected.get("statusCounts", {})
    for status in sorted(ALLOWED_STATUS):
        if declared_counts.get(status, 0) != status_counts.get(status, 0):
            errors.append(f"statusCounts.{status} does not match expected.sections")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--review", action="append", required=True)
    args = parser.parse_args()
    provenance = load(args.provenance)
    all_errors = []
    reviewed = []
    for path in args.review:
        review = load(path)
        errors = validate_review(review, provenance)
        reviewed.append({"path": path, "chapterNumber": review.get("chapterNumber"), "errors": errors})
        all_errors.extend(f"{path}: {error}" for error in errors)
    result = {"valid": not all_errors, "reviewCount": len(reviewed), "reviews": reviewed, "errors": all_errors}
    print(json.dumps(result, indent=2))
    return 0 if not all_errors else 1


if __name__ == "__main__":
    sys.exit(main())
