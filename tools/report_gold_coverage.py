#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

TARGETS = {
    "single-ors-amendment": 8,
    "multiple-ors-amendments": 8,
    "ors-repeal": 5,
    "mixed-amendment-repeal": 4,
    "negative-control": 5,
    "uncodified-session-law-amendment": 4,
    "added-to-provision": 4,
    "lettered-ors-chapter": 3,
    "prior-session-law-cross-reference": 3,
    "special-session": 3,
    "degraded-layout": 3,
    "title-body-edge-case": 3,
}

ALIASES = {
    "no-ors-change": "negative-control",
    "incidental-ors-citations": "title-body-edge-case",
    "conditional-amendments": "title-body-edge-case",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    documents = manifest.get("documents", [])

    counts = {key: 0 for key in TARGETS}
    for item in documents:
        tags = set(item.get("caseTags", []))
        expanded = set(tags)
        expanded.update(ALIASES[tag] for tag in tags if tag in ALIASES)
        for key in TARGETS:
            if key in expanded:
                counts[key] += 1

    coverage = []
    for key, target in TARGETS.items():
        count = counts[key]
        coverage.append({
            "category": key,
            "count": count,
            "target": target,
            "remaining": max(0, target - count),
            "targetMet": count >= target,
        })

    report = {
        "schemaVersion": 1,
        "documentCount": len(documents),
        "releaseCertificationMinimumDocuments": manifest.get("releaseCertificationMinimumDocuments", 50),
        "documentsRemainingToMinimum": max(0, manifest.get("releaseCertificationMinimumDocuments", 50) - len(documents)),
        "categoriesMeetingTarget": sum(1 for item in coverage if item["targetMet"]),
        "categoryCount": len(coverage),
        "coverage": coverage,
        "priorityGaps": [
            item["category"]
            for item in sorted(coverage, key=lambda x: (-x["remaining"], x["category"]))
            if item["remaining"] > 0
        ],
    }

    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
