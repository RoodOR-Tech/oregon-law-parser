"""Link general ORS notices through a source-reviewed amendment-table snapshot.

This supplements the printed notice, never rewrites it or applies amendments.
Matching a result file does not verify its section-level amendment semantics.
"""
import argparse
import json
import re
from pathlib import Path

from reconcile_pending_changes import index_session_results, read_ndjson


def review_index(review):
    if review.get("schemaVersion") != 1 or type(review.get("sessionYear")) is not int:
        raise ValueError("review requires schemaVersion 1 and integer sessionYear")
    source = review.get("source", {})
    if (not str(source.get("url", "")).startswith("https://")
            or not re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", ""))
            or type(source.get("bytes")) is not int or source["bytes"] <= 0
            or not source.get("retrievedAt")):
        raise ValueError("review requires source URL, SHA-256, bytes and retrieval time")
    chapters = review.get("reviewedChapters", [])
    if not chapters or len(chapters) != len(set(chapters)):
        raise ValueError("review requires unique reviewed chapters")
    indexed = {chapter: [] for chapter in chapters}
    seen = set()
    for ref in review.get("references", []):
        match = re.fullmatch(r"(\d+[A-Z]?)\.\d{3}", ref.get("orsSection", ""))
        if (not match or match[1] not in indexed or ref.get("action") not in ("A", "R")
                or type(ref.get("sessionLawChapter")) is not int or ref["sessionLawChapter"] <= 0
                or not re.fullmatch(r"\d+[a-z]?", ref.get("sessionLawSection", ""))
                or type(ref.get("page")) is not int or ref["page"] <= 0):
            raise ValueError("invalid amendment-table reference")
        key = (ref["orsSection"], ref["action"], ref["sessionLawChapter"], ref["sessionLawSection"])
        if key in seen:
            raise ValueError("duplicate amendment-table reference")
        seen.add(key)
        indexed[match[1]].append(ref)
    if any(not refs for refs in indexed.values()):
        raise ValueError("reviewed chapter has no amendment-table references")
    return indexed


def resolve(pending_rows, review, results):
    indexed = review_index(review)
    rows = []
    for pending in pending_rows:
        if (pending.get("session_law_chapter") is not None
                or pending.get("change_kind") != "amended_or_repealed_elsewhere"):
            continue
        chapter = str(pending.get("chapter_id", "")).partition("-")[2]
        refs = indexed.get(chapter, []) if pending.get("session_year") == review["sessionYear"] else []
        matches = []
        for ref in refs:
            result = results.get((review["sessionYear"], ref["sessionLawChapter"]))
            status = "missing-session-result" if result is None else (
                "matched-parsed" if result["status"] == "parsed" else "matched-parser-error")
            matches.append({**ref, "status": status,
                            "sessionResultPath": result["path"] if result else None})
        rows.append({"pendingChangeId": pending.get("pending_change_id"),
                     "orsChapterId": pending.get("chapter_id"),
                     "sessionYear": pending.get("session_year"),
                     "status": "matched-reviewed-references" if matches and all(
                         m["status"] == "matched-parsed" for m in matches) else "unresolved",
                     "references": matches})
    resolved = sum(row["status"] == "matched-reviewed-references" for row in rows)
    return {"schemaVersion": 1, "source": review["source"],
            "scope": "Source-reviewed notice-to-result links; no amendment application or section-level parser verification.",
            "generalNoticeCount": len(rows), "resolvedNoticeCount": resolved,
            "unresolvedNoticeCount": len(rows) - resolved,
            "matchedReferenceCount": sum(ref["status"] == "matched-parsed" for row in rows for ref in row["references"]),
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pending", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--session-results-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = resolve(read_ndjson(args.pending), json.loads(Path(args.review).read_text(encoding="utf-8")),
                     index_session_results(args.session_results_dir))
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
