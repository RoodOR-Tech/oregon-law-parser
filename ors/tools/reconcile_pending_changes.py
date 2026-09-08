#!/usr/bin/env python3
"""Reconcile ORS pending-change rows against session-law parser result files.

The join key is the printed pending-change tuple (session_year,
session_law_chapter). Parser result identity comes from the established
operational filename convention: YYYYorlaw####.json. This tool does not infer
that a non-specific chapter notice changed any particular Oregon Laws chapter.
"""
import argparse
import json
import re
from pathlib import Path

RESULT_RE = re.compile(r"^(?P<year>\d{4})orlaw(?P<chapter>\d{4})\.json$")


def read_ndjson(path):
    rows = []
    for line_no, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object")
        rows.append(row)
    return rows


def index_session_results(results_dir):
    indexed = {}
    for path in sorted(Path(results_dir).glob("*.json")):
        match = RESULT_RE.match(path.name)
        if not match:
            continue
        key = (int(match.group("year")), int(match.group("chapter")))
        if key in indexed:
            raise ValueError(f"duplicate session result identity: {key[0]} c.{key[1]}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            parser_error = isinstance(payload, dict) and bool(payload.get("errors"))
            status = "parser-error" if parser_error else "parsed"
        except Exception as exc:
            payload = None
            status = "invalid-json"
            parser_error = True
            error = str(exc)
        indexed[key] = {
            "path": str(path),
            "status": status,
            "parserError": parser_error,
            **({"error": error} if status == "invalid-json" else {}),
        }
    return indexed


def reconcile(pending_rows, session_results):
    rows = []
    counts = {
        "matchedParsed": 0,
        "matchedParserError": 0,
        "missingResult": 0,
        "nonSpecificNotice": 0,
    }
    for pending in pending_rows:
        year = pending.get("session_year")
        chapter = pending.get("session_law_chapter")
        base = {
            "pending_change_id": pending.get("pending_change_id"),
            "ors_chapter_id": pending.get("chapter_id"),
            "change_kind": pending.get("change_kind"),
            "session_year": year,
            "session_law_chapter": chapter,
        }
        if chapter is None:
            base["reconciliation_status"] = "non-specific-notice"
            counts["nonSpecificNotice"] += 1
        else:
            if not isinstance(year, int) or not isinstance(chapter, int):
                raise ValueError("chapter-specific pending change requires integer session_year and session_law_chapter")
            result = session_results.get((year, chapter))
            if result is None:
                base["reconciliation_status"] = "missing-session-result"
                counts["missingResult"] += 1
            elif result["status"] == "parsed":
                base["reconciliation_status"] = "matched-parsed"
                base["session_result_path"] = result["path"]
                counts["matchedParsed"] += 1
            else:
                base["reconciliation_status"] = "matched-parser-error"
                base["session_result_path"] = result["path"]
                base["session_result_status"] = result["status"]
                if "error" in result:
                    base["session_result_error"] = result["error"]
                counts["matchedParserError"] += 1
        rows.append(base)

    specific = counts["matchedParsed"] + counts["matchedParserError"] + counts["missingResult"]
    return {
        "schemaVersion": 1,
        "pendingChangeCount": len(pending_rows),
        "chapterSpecificNoticeCount": specific,
        "nonSpecificNoticeCount": counts["nonSpecificNotice"],
        "matchedParsedCount": counts["matchedParsed"],
        "matchedParserErrorCount": counts["matchedParserError"],
        "missingSessionResultCount": counts["missingResult"],
        "completeForAvailableSessionResults": counts["matchedParserError"] == 0,
        "allChapterSpecificNoticesResolved": counts["matchedParserError"] == 0 and counts["missingResult"] == 0,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", required=True, help="ors_chapter_pending_change NDJSON")
    parser.add_argument("--session-results-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = reconcile(read_ndjson(args.pending), index_session_results(args.session_results_dir))
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
