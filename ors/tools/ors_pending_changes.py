#!/usr/bin/env python3
"""Parse printed ORS chapter pending-change notices into deterministic rows.

The parser is intentionally narrow: it extracts only notices printed above the
edition heading and never infers changes from parser output or session-law data.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Iterable

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SESSION_RE = re.compile(r"during its\s+(\d{4})\s+(regular|special)\s+session", re.I)
CHAPTER_RE = re.compile(r"Session Laws\s+0*(\d+)", re.I)

NOTICE_TYPES = (
    (
        "amended_or_repealed",
        "ORS sections in this chapter were amended or repealed",
    ),
    (
        "added_to_chapter_or_series",
        "New sections of law were added by legislative action to this ORS chapter or to a series within this ORS chapter",
    ),
    (
        "likely_compiled_in_chapter",
        "New sections of law were enacted by the Legislative Assembly",
    ),
)


def visible_text(markup: str) -> str:
    text = TAG_RE.sub(" ", markup)
    text = html.unescape(text).replace("\xa0", " ")
    return SPACE_RE.sub(" ", text).strip()


def _notice_chunks(markup: str) -> Iterable[tuple[str, str]]:
    # Pending-change notices occur before the edition heading. Restrict parsing
    # to that prefix so ordinary chapter body references cannot become notices.
    prefix = re.split(r"\b20\d{2}\s+EDITION\b", visible_text(markup), maxsplit=1, flags=re.I)[0]
    starts = []
    for notice_type, marker in NOTICE_TYPES:
        idx = prefix.find(marker)
        if idx >= 0:
            starts.append((idx, notice_type))
    starts.sort()
    for i, (start, notice_type) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(prefix)
        yield notice_type, prefix[start:end].strip()


def parse_pending_changes(markup: str, edition_id: str, chapter_number: str) -> list[dict]:
    rows: list[dict] = []
    ordinal = 0
    for notice_type, text in _notice_chunks(markup):
        session = SESSION_RE.search(text)
        if not session:
            raise ValueError(f"pending-change notice lacks session identity: {text}")
        session_year = int(session.group(1))
        session_kind = session.group(2).lower()
        chapters = [int(x) for x in CHAPTER_RE.findall(text)]
        if notice_type == "amended_or_repealed":
            chapters = [None]
        elif not chapters:
            raise ValueError(f"pending-change notice lacks Oregon Laws chapter: {text}")
        for session_law_chapter in chapters:
            ordinal += 1
            rows.append(
                {
                    "pending_change_id": f"{edition_id}-{chapter_number}-pc{ordinal:03d}",
                    "edition_id": edition_id,
                    "chapter_number": chapter_number,
                    "ordinal": ordinal,
                    "notice_kind": notice_type,
                    "session_year": session_year,
                    "session_kind": session_kind,
                    "session_law_chapter": session_law_chapter,
                    "raw_notice": text,
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("html_file", type=Path)
    parser.add_argument("--edition-id", required=True)
    parser.add_argument("--chapter-number", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    markup = args.html_file.read_text(encoding="utf-8", errors="replace")
    rows = parse_pending_changes(markup, args.edition_id, args.chapter_number)
    payload = "\n".join(json.dumps(row, sort_keys=True) for row in rows) + ("\n" if rows else "")
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
