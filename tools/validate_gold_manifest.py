#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_REVIEW_STATUSES = {"independently-reviewed"}
ALLOWED_SOURCE_HOSTS = {
    "www.oregonlegislature.gov",
    "oregonlegislature.gov",
    "olis.oregonlegislature.gov",
}
REQUIRED_EXPECTED_KEYS = {"year", "chapter", "bill", "effectiveDate", "affectedSections"}


def validate_document(item, repo_root):
    errors = []
    doc_id = item.get("id", "<missing-id>")

    for key in ("id", "fixture", "sourceUrl", "reviewStatus", "reviewBasis", "reviewSources", "expected"):
        if key not in item:
            errors.append(f"{doc_id}: missing required field {key}")

    if item.get("reviewStatus") not in ALLOWED_REVIEW_STATUSES:
        errors.append(f"{doc_id}: reviewStatus must be independently-reviewed")

    review_basis = item.get("reviewBasis", "")
    if not isinstance(review_basis, str) or len(review_basis.strip()) < 40:
        errors.append(f"{doc_id}: reviewBasis must explain the independent verification basis")

    review_sources = item.get("reviewSources", [])
    if not isinstance(review_sources, list) or not review_sources:
        errors.append(f"{doc_id}: reviewSources must contain at least one authoritative source")
    else:
        for source in review_sources:
            try:
                host = urlparse(source).hostname
            except Exception:
                host = None
            if host not in ALLOWED_SOURCE_HOSTS:
                errors.append(f"{doc_id}: non-authoritative review source host: {host!r}")

    source_url = item.get("sourceUrl")
    if source_url:
        host = urlparse(source_url).hostname
        if host not in ALLOWED_SOURCE_HOSTS:
            errors.append(f"{doc_id}: sourceUrl host is not an approved Oregon legislative host: {host!r}")

    fixture = item.get("fixture")
    if fixture and not (repo_root / fixture).is_file():
        errors.append(f"{doc_id}: fixture does not exist: {fixture}")

    expected = item.get("expected", {})
    missing_expected = REQUIRED_EXPECTED_KEYS - set(expected)
    for key in sorted(missing_expected):
        errors.append(f"{doc_id}: expected missing {key}")

    affected = expected.get("affectedSections", {})
    for action in ("amended", "repealed"):
        values = affected.get(action)
        if not isinstance(values, list):
            errors.append(f"{doc_id}: expected.affectedSections.{action} must be an array")
        elif len(values) != len(set(values)):
            errors.append(f"{doc_id}: duplicate {action} ORS section labels")

    case_tags = item.get("caseTags", [])
    if not isinstance(case_tags, list) or not case_tags:
        errors.append(f"{doc_id}: caseTags must identify at least one corpus coverage characteristic")

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    repo_root = Path(args.repo_root)
    manifest = json.loads(manifest_path.read_text())

    errors = []
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        errors.append("manifest.documents must be a non-empty array")
        documents = []

    ids = [item.get("id") for item in documents]
    if len(ids) != len(set(ids)):
        errors.append("manifest contains duplicate document ids")

    for item in documents:
        errors.extend(validate_document(item, repo_root))

    report = {
        "schemaVersion": 1,
        "documentCount": len(documents),
        "valid": not errors,
        "errors": errors,
        "coverageTags": sorted({tag for item in documents for tag in item.get("caseTags", [])}),
    }
    print(json.dumps(report, indent=2))

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
