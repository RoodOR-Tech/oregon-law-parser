"""Build a separate, source-reviewed amendment preview without editing ORS rows."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def row_digest(row):
    return digest(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_preview(base, plan, verification, as_of):
    require(base.get("schemaVersion") == plan.get("schemaVersion") == 1, "unsupported schema")
    section = base["section"]
    require(section.get("section_id") == plan.get("baseSectionId")
            and section.get("section_number") == plan.get("orsSection"), "base section identity mismatch")
    require(row_digest(section) == plan.get("baseRowSha256"), "base row changed since review")
    require(base["source"]["sha256"] == plan.get("baseSourceSha256"), "base source changed since review")
    require(plan.get("action") == "A", "only reviewed amendments are supported")
    require(section.get("status") == "operative", "base section is not operative")
    effective = date.fromisoformat(plan["effectiveDate"])
    operative = date.fromisoformat(plan["operativeDate"])
    require(operative >= effective, "operative date precedes effective date")
    require(date.fromisoformat(as_of) >= operative, "amendment is not yet operative as of requested date")
    require(verification.get("gatePassed") is True, "section verification gate did not pass")
    keys = ("orsSection", "sessionYear", "sessionLawChapter", "sessionLawSection", "action", "measure")
    matches = [r for r in verification.get("rows", []) if all(r.get(k) == plan.get(k) for k in keys)]
    require(len(matches) == 1 and matches[0].get("status") == "exact-match", "exact reviewed reference required")
    provenance = matches[0].get("parserProvenance") or {}
    require(provenance.get("sourceSha256") == plan["lawSource"]["sha256"]
            and provenance.get("sourceUrl") == plan["lawSource"]["url"], "amendment source changed since review")
    edit = plan["edit"]
    require(edit.get("occurrences") == 1 and isinstance(edit.get("old"), str) and bool(edit["old"])
            and isinstance(edit.get("new"), str), "one explicit reviewed replacement required")
    require(section["body_text"].count(edit["old"]) == 1, "replacement target must occur exactly once")
    proposed = section["body_text"].replace(edit["old"], edit["new"], 1)
    require(digest(" ".join(proposed.split())) == plan.get("expectedNormalizedBodySha256"),
            "proposed body disagrees with independently reviewed enacted text")
    return {"schemaVersion": 1, "previewId": plan["previewId"], "status": "reviewed-preview",
            "scope": plan["scope"], "asOf": as_of,
            "effectiveDate": plan["effectiveDate"], "operativeDate": plan["operativeDate"],
            "baseSectionId": section["section_id"], "baseRowSha256": row_digest(section),
            "baseSource": base["source"], "amendmentSource": plan["lawSource"],
            "appliedReference": {k: plan[k] for k in keys},
            "sectionNumber": section["section_number"], "catchline": section["catchline"],
            "beforeBodyText": section["body_text"], "proposedBodyText": proposed,
            "proposedBodySha256": digest(proposed), "edit": dict(edit)}


def render_markdown(report):
    return (f"# ORS {report['sectionNumber']} amendment preview\n\n"
            f"{report['scope']}\n\n"
            f"As of: {report['asOf']}. Effective/operative: {report['operativeDate']}.\n\n"
            f"Before: {report['edit']['old']}\n\nAfter: {report['edit']['new']}\n\n"
            f"[Published ORS source]({report['baseSource']['sourceUrl']}) · "
            f"[Session law, §{report['appliedReference']['sessionLawSection']}]({report['amendmentSource']['url']})\n\n"
            f"## Proposed body\n\n{report['proposedBodyText']}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "plan", "verification", "as-of", "report"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--markdown")
    args = parser.parse_args()
    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    report = build_preview(read(args.base), read(args.plan), read(args.verification), args.as_of)
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("previewId", "status", "asOf", "proposedBodySha256")}))


if __name__ == "__main__":
    main()
