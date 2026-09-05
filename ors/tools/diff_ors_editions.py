#!/usr/bin/env python3
"""Diff canonical ORS section rows between two published editions.

This tool is intentionally data-only. It compares the canonical NDJSON section
rows emitted by the relational build and does not import the session-law parser.
The output is a deterministic JSON report suitable for later reconciliation
against amendment-parser results.
"""
import argparse
import json
from pathlib import Path

COMPARE_FIELDS = ("catchline", "body_text", "status", "renumbered_to")


def read_ndjson(path):
    rows = []
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        number = row.get("section_number")
        if not isinstance(number, str) or not number:
            raise ValueError(f"{path}:{line_no}: missing section_number")
        rows.append(row)
    return rows


def index_rows(rows, label):
    indexed = {}
    for row in rows:
        number = row["section_number"]
        if number in indexed:
            raise ValueError(f"duplicate section_number in {label}: {number}")
        indexed[number] = row
    return indexed


def field_changes(before, after):
    changes = {}
    for field in COMPARE_FIELDS:
        left = before.get(field)
        right = after.get(field)
        if left != right:
            changes[field] = {"before": left, "after": right}
    return changes


def diff_sections(before_rows, after_rows, before_edition, after_edition):
    before = index_rows(before_rows, "before edition")
    after = index_rows(after_rows, "after edition")
    all_numbers = sorted(set(before) | set(after))

    added, removed, changed, unchanged = [], [], [], []
    for number in all_numbers:
        left = before.get(number)
        right = after.get(number)
        if left is None:
            added.append({"sectionNumber": number, "after": right})
        elif right is None:
            removed.append({"sectionNumber": number, "before": left})
        else:
            changes = field_changes(left, right)
            if changes:
                changed.append({
                    "sectionNumber": number,
                    "changes": changes,
                    "beforeSectionId": left.get("section_id"),
                    "afterSectionId": right.get("section_id"),
                })
            else:
                unchanged.append(number)

    report = {
        "schemaVersion": 1,
        "beforeEdition": str(before_edition),
        "afterEdition": str(after_edition),
        "beforeSectionCount": len(before),
        "afterSectionCount": len(after),
        "addedCount": len(added),
        "removedCount": len(removed),
        "changedCount": len(changed),
        "unchangedCount": len(unchanged),
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchangedSectionNumbers": unchanged,
        "reconciliation": {
            "status": "not-run",
            "note": "Reserved for reconciliation against amendment-parser output for intervening sessions."
        },
    }
    report["valid"] = (
        report["beforeSectionCount"] == report["removedCount"] + report["changedCount"] + report["unchangedCount"]
        and report["afterSectionCount"] == report["addedCount"] + report["changedCount"] + report["unchangedCount"]
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-sections", required=True)
    parser.add_argument("--after-sections", required=True)
    parser.add_argument("--before-edition", required=True)
    parser.add_argument("--after-edition", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    report = diff_sections(
        read_ndjson(args.before_sections),
        read_ndjson(args.after_sections),
        args.before_edition,
        args.after_edition,
    )
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "valid", "beforeSectionCount", "afterSectionCount", "addedCount",
        "removedCount", "changedCount", "unchangedCount"
    )}))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
