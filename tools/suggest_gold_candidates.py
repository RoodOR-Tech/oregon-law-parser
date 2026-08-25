#!/usr/bin/env python3
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def classify(actions, sections):
    tags = []
    actions = set(actions)
    if "amended" in actions and "repealed" in actions:
        tags.append("mixed-amendment-repeal")
    elif "repealed" in actions:
        tags.append("ors-repeal")
    elif "amended" in actions:
        tags.append("multiple-ors-amendments" if len(sections) > 1 else "single-ors-amendment")
    if "added_to" in actions:
        tags.append("added-to-provision")
    if any(any(ch.isalpha() for ch in section.split(".", 1)[0]) for section in sections):
        tags.append("lettered-ors-chapter")
    return tags


def main():
    parser = argparse.ArgumentParser(description="Suggest gold-corpus candidates from normalized Legislative Counsel rows. This tool never creates gold labels.")
    parser.add_argument("--lc-csv", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    existing = {(str(item["expected"]["year"]), str(item["expected"]["chapter"])) for item in manifest.get("documents", [])}

    grouped = defaultdict(list)
    with Path(args.lc_csv).open(newline="") as handle:
        for row in csv.DictReader(handle):
            key = (row["source_year"], row["oregon_laws_chapter"])
            grouped[key].append(row)

    candidates = []
    for (year, chapter), rows in sorted(grouped.items(), key=lambda x: (int(x[0][0]), int(x[0][1]))):
        if (year, chapter) in existing:
            continue
        actions = [row["action"] for row in rows]
        sections = sorted({row["ors_section"] for row in rows if row.get("ors_section")})
        candidates.append({
            "sourceYear": int(year),
            "oregonLawsChapter": int(chapter),
            "actionsSeen": sorted(set(actions)),
            "orsSectionsSeen": sections,
            "suggestedCaseTags": classify(actions, sections),
            "sourceUrls": sorted({row["source_url"] for row in rows if row.get("source_url")}),
            "warning": "Candidate metadata only. Independently review the enacted session law and authoritative sources before adding any gold expectation.",
        })

    report = {
        "schemaVersion": 1,
        "candidateCount": len(candidates),
        "candidates": candidates,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
