"""Publish dated reviewed previews with explicit gaps in the reviewed reference set."""
import argparse
from datetime import date
import json
from pathlib import Path

from build_amendment_preview import require
from build_preview_batch import build_batch, write_batch


REFERENCE_KEYS = ("orsSection", "sessionYear", "sessionLawChapter", "sessionLawSection", "action", "measure")


def reference_key(row):
    return tuple(row[k] for k in REFERENCE_KEYS)


def build_catalog(entries, verification, as_of):
    date.fromisoformat(as_of)
    rows = verification.get("rows", [])
    require(verification.get("schemaVersion") == 1 and verification.get("gatePassed") is True,
            "successful section verification required")
    require(bool(rows) and verification.get("referenceCount") == len(rows)
            and verification.get("exactMatchCount") == len(rows)
            and all(row.get("status") == "exact-match" for row in rows),
            "verification rows and counts disagree")
    references = {}
    identities = set()
    for row in rows:
        key = reference_key(row)
        require(key[:-1] not in identities, "duplicate verified reference")
        identities.add(key[:-1])
        references[key] = row
    plans = {}
    for entry in entries:
        plan = entry["plan"]
        key = reference_key(plan)
        require(key in references, "plan has no verified reference")
        require(key not in plans, "multiple plans for one verified reference")
        plans[key] = plan
    # Pending plans are reviewed claims too. Validate the entire history at its
    # final operative date before publishing even an earlier dated collection.
    if entries:
        horizon = max(entry["plan"]["operativeDate"] for entry in entries)
        build_batch(entries, verification, horizon)
    batch = build_batch(entries, verification, as_of)
    applied = {p["previewId"] for p in batch["previews"]}
    coverage = []
    for key, row in sorted(references.items()):
        plan = plans.get(key)
        coverage.append({**{k: row[k] for k in REFERENCE_KEYS},
            "reviewSource": row.get("reviewSource"), "parserProvenance": row.get("parserProvenance"),
            "status": ("needs-text-review" if plan is None else
                       "applied-preview" if plan["previewId"] in applied else "scheduled"),
            "previewId": plan["previewId"] if plan else None,
            "effectiveDate": plan["effectiveDate"] if plan else None,
            "operativeDate": plan["operativeDate"] if plan else None})
    bases = {b["section"]["section_number"]: b for b in batch["originalBases"]}
    sections = []
    for number in sorted({r["orsSection"] for r in rows}):
        base = bases.get(number)
        missing = sum(r["orsSection"] == number and r["status"] == "needs-text-review" for r in coverage)
        sections.append({"orsSection": number,
            "baseSectionId": base["section"]["section_id"] if base else None,
            "latestReviewedPreviewId": batch["currentPreviewBySection"].get(base["section"]["section_id"]) if base else None,
            "knownReferencesWithoutPlans": missing,
            "baseAvailable": base is not None})
    return {"schemaVersion": 1, "asOf": as_of,
        "scope": "Reviewed references and explicit text plans only. Missing plans have unreviewed dates. Latest preview does not certify current law or complete amendment coverage.",
        "verifiedReferenceCount": len(rows), "plannedReferenceCount": len(plans),
        "referencesNeedingTextReview": len(rows) - len(plans),
        "allReviewedReferencesHavePlans": len(rows) == len(plans),
        "appliedPreviewCount": batch["previewCount"], "scheduledPreviewCount": batch["pendingCount"],
        "coverage": coverage, "sections": sections, "batch": batch}


def render_catalog(report):
    lines = ["# Reviewed ORS amendment collection", "", f"As of: {report['asOf']}", "", report["scope"], "",
        f"{report['verifiedReferenceCount']} verified references; {report['plannedReferenceCount']} reviewed text plans; "
        f"{report['referencesNeedingTextReview']} references still need text/date review.", "",
        f"{report['appliedPreviewCount']} applied previews; {report['scheduledPreviewCount']} scheduled previews.", "",
        "| ORS section | Session law | Measure | Review status | Operative date |",
        "| --- | --- | --- | --- | --- |"]
    for row in report["coverage"]:
        law = f"{row['sessionYear']} c.{row['sessionLawChapter']} §{row['sessionLawSection']}"
        url = (row.get("parserProvenance") or {}).get("sourceUrl")
        if url:
            law = f"[{law}]({url})"
        lines.append(f"| {row['orsSection']} | {law} | {row['measure']} | {row['status']} | {row['operativeDate'] or 'Not reviewed'} |")
    lines.extend(["", "Every applied version and original base is retained in catalog.json and previews/batch.json.",
                  "References without a text plan are not silently treated as unchanged or inapplicable.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--verification", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", required=True, help="new directory; existing output is never overwritten")
    args = parser.parse_args()
    read = lambda p: json.loads(Path(p).read_text(encoding="utf-8"))
    manifest_path = Path(args.manifest)
    manifest = read(manifest_path)
    require(manifest.get("schemaVersion") == 1, "unsupported catalog manifest schema")
    entries = [{"base": read(manifest_path.parent / e["base"]),
                "plan": read(manifest_path.parent / e["plan"])} for e in manifest["entries"]]
    report = build_catalog(entries, read(args.verification), args.as_of)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=False)
    write_batch(report["batch"], output / "previews")
    (output / "catalog.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "catalog.md").write_text(render_catalog(report), encoding="utf-8")
    print(json.dumps({"amendmentPreviewCatalog": report}))


if __name__ == "__main__":
    main()
