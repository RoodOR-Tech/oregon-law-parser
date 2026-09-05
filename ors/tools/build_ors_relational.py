#!/usr/bin/env python3
"""Emit SCHEMA.md's relational tables as NDJSON, CSV and a SQLite database.

Every earlier tool in this pipeline speaks its own tool-shaped JSON, in
camelCase, keyed by whatever that stage's own logic needed
(`chapterNumber`, `sourceSha256`, ...). This is the one place those three
reports -- the roster (`acquire_ors_roster.py`), the acquisition ledger
(`acquire_ors_chapters.py`) and the parsed rows (`parse_ors_chapter.py`'s
`--rows` output) -- are joined into SCHEMA.md's own tables, with SCHEMA.md's
own snake_case column names. Referential integrity is not re-checked here:
`parse_ors_chapter.py`'s own gate already covers the rows it produces, and
this module only reshapes and joins, it does not invent new facts.

Two joins are worth naming, since neither report on its own carries what
SCHEMA.md's tables need:

- `ors_chapter.source_format` and `.retrieved_at` are not in `rows.json`'s
  own chapter rows (parsing only carries forward what parsing itself
  needs); they come from the acquisition ledger's per-chapter record,
  matched by chapter number.
- `ors_acquisition_event.edition_id` is not knowable from the acquisition
  ledger alone -- edition identity is established from a chapter's own
  content, after the fact (see FINDINGS.md), and the roster fetch predates
  any chapter fetch entirely. Every routine build in this pipeline parses
  exactly one edition's chapters (a rebuild for a new edition is its own
  separate run, per ROADMAP.md's working method), so every acquisition
  event -- the roster fetch included -- is filed under that one edition.
  A chapter fetch that produced a real parsed chapter uses that chapter's
  own edition_id; one that never got that far (a failed fetch, or a fetch
  parsing rejected) falls back to the build's one edition, the same
  simplifying assumption `parse_ors_chapter.py`'s own cross-reference
  resolution already makes for its `section_ids_by_number` map.
"""
import argparse
import csv
import json
import sqlite3
from pathlib import Path


def _volume_id(edition_id, volume_number):
    if volume_number is None:
        return None
    return f"{edition_id}-v{int(volume_number):02d}"


def _title_id(edition_id, title_number):
    if title_number is None:
        return None
    return f"{edition_id}-t{title_number}"


def build_edition_rows(rows, roster):
    """`ors_edition`: rows.json's own editions, plus the roster's own
    index provenance -- the roster is one document shared by every edition
    this build parses (see module docstring for why that is always one)."""
    result = []
    for edition in rows.get("editions", []):
        result.append({
            "edition_id": edition["editionId"],
            "edition_year": edition["editionYear"],
            "index_url": roster.get("rosterUrl"),
            "index_sha256": roster.get("rosterSha256"),
            "index_bytes": roster.get("rosterBytes"),
            "retrieved_at": roster.get("retrievedAt"),
            "chapter_count": edition["chapterCount"],
        })
    return sorted(result, key=lambda item: item["edition_id"])


def build_volume_rows(edition_id, roster):
    result = []
    for volume in roster.get("volumes", []):
        result.append({
            "volume_id": _volume_id(edition_id, volume["volumeNumber"]),
            "edition_id": edition_id,
            "volume_number": volume["volumeNumber"],
            "first_chapter": volume.get("firstChapter"),
            "last_chapter": volume.get("lastChapter"),
        })
    return sorted(result, key=lambda item: item["volume_id"])


def build_title_rows(edition_id, roster):
    result = []
    for title in roster.get("titles", []):
        result.append({
            "title_id": _title_id(edition_id, title["titleNumber"]),
            "edition_id": edition_id,
            "title_number": title["titleNumber"],
            "title_name": title.get("titleName"),
        })
    return sorted(result, key=lambda item: item["title_id"])


def build_chapter_rows(rows, acquisition):
    """`ors_chapter`: rows.json's own chapters, joined to the acquisition
    ledger for source_format and retrieved_at (see module docstring)."""
    acquired_by_number = {
        chapter["chapterNumber"]: chapter for chapter in acquisition.get("chapters", [])
    }
    result = []
    for chapter in rows.get("chapters", []):
        acquired = acquired_by_number.get(chapter["chapterNumber"], {})
        result.append({
            "chapter_id": chapter["chapterId"],
            "edition_id": chapter["editionId"],
            "title_id": _title_id(chapter["editionId"], chapter.get("titleNumber")),
            "volume_id": _volume_id(chapter["editionId"], chapter.get("volumeNumber")),
            "chapter_number": chapter["chapterNumber"],
            "chapter_sort_key": chapter["chapterSortKey"],
            "chapter_name": chapter.get("chapterName"),
            "source_url": chapter.get("sourceUrl"),
            "source_format": acquired.get("sourceFormat"),
            "source_sha256": chapter.get("sourceSha256"),
            "source_bytes": chapter.get("sourceBytes"),
            "retrieved_at": acquired.get("retrievedAt"),
        })
    return sorted(result, key=lambda item: item["chapter_id"])


def build_subdivision_rows(rows):
    result = [
        {
            "subdivision_id": item["subdivisionId"],
            "chapter_id": item["chapterId"],
            "heading_text": item["headingText"],
            "ordinal": item["ordinal"],
            "char_offset_start": item["charOffsetStart"],
            "char_offset_end": item["charOffsetEnd"],
        }
        for item in rows.get("subdivisions", [])
    ]
    return sorted(result, key=lambda item: item["subdivision_id"])


def build_section_rows(rows):
    result = [
        {
            "section_id": item["sectionId"],
            "chapter_id": item["chapterId"],
            "subdivision_id": item.get("subdivisionId"),
            "section_number": item["sectionNumber"],
            "section_sort_key": item["sectionSortKey"],
            "catchline": item.get("catchline"),
            "body_text": item.get("bodyText"),
            "status": item["status"],
            "renumbered_to": item.get("renumberedTo"),
            "ordinal": item["ordinal"],
            "char_offset_start": item["charOffsetStart"],
            "char_offset_end": item["charOffsetEnd"],
        }
        for item in rows.get("sections", [])
    ]
    return sorted(result, key=lambda item: item["section_id"])


def build_section_note_rows(rows):
    result = [
        {
            "note_id": item["noteId"],
            "section_id": item["sectionId"],
            "note_kind": item["noteKind"],
            "note_text": item["noteText"],
            "ordinal": item["ordinal"],
            "char_offset_start": item["charOffsetStart"],
            "char_offset_end": item["charOffsetEnd"],
        }
        for item in rows.get("sectionNotes", [])
    ]
    return sorted(result, key=lambda item: item["note_id"])


def build_source_credit_rows(rows):
    result = [
        {
            "credit_id": item["creditId"],
            "section_id": item["sectionId"],
            "ordinal": item["ordinal"],
            "session_year": item["sessionYear"],
            "session_law_chapter": item["sessionLawChapter"],
            "session_law_section": item.get("sessionLawSection"),
            "special_session": item.get("specialSession"),
            "action": item["action"],
            "raw_credit": item["rawCredit"],
        }
        for item in rows.get("sourceCredits", [])
    ]
    return sorted(result, key=lambda item: item["credit_id"])


def build_pending_change_rows(rows):
    result = [
        {
            "pending_change_id": item["pendingChangeId"],
            "chapter_id": item["chapterId"],
            "ordinal": item["ordinal"],
            "session_year": item["sessionYear"],
            "session_law_chapter": item.get("sessionLawChapter"),
            "change_kind": item["changeKind"],
            "notice_text": item["noticeText"],
            "char_offset_start": item["charOffsetStart"],
            "char_offset_end": item["charOffsetEnd"],
        }
        for item in rows.get("pendingChanges", [])
    ]
    return sorted(result, key=lambda item: item["pending_change_id"])


def build_cross_reference_rows(rows):
    result = [
        {
            "reference_id": item["referenceId"],
            "from_section_id": item["fromSectionId"],
            "to_section_number": item["toSectionNumber"],
            "to_section_id": item.get("toSectionId"),
            "reference_kind": item["referenceKind"],
            "ordinal": item["ordinal"],
            "char_offset_start": item["charOffsetStart"],
            "char_offset_end": item["charOffsetEnd"],
        }
        for item in rows.get("crossReferences", [])
    ]
    return sorted(result, key=lambda item: item["reference_id"])


def build_acquisition_event_rows(rows, roster, acquisition):
    """`ors_acquisition_event`: see module docstring for the edition_id join."""
    editions = rows.get("editions", [])
    default_edition_id = editions[0]["editionId"] if len(editions) == 1 else None
    edition_by_chapter = {
        chapter["chapterNumber"]: chapter["editionId"] for chapter in rows.get("chapters", [])
    }

    result = []

    index_ok = bool(roster.get("rosterSha256"))
    result.append({
        "event_id": f"{default_edition_id or 'unknown'}-idx",
        "edition_id": default_edition_id,
        "chapter_number": None,
        "requested_url": roster.get("rosterUrl"),
        "ok": 1 if index_ok else 0,
        "http_status": roster.get("rosterHttpStatus"),
        "sha256": roster.get("rosterSha256"),
        "bytes": roster.get("rosterBytes"),
        "attempts": roster.get("rosterAttempts"),
        "error": None if index_ok else roster.get("error"),
        "retrieved_at": roster.get("retrievedAt"),
    })

    for chapter in acquisition.get("chapters", []):
        number = chapter["chapterNumber"]
        edition_id = edition_by_chapter.get(number, default_edition_id)
        result.append({
            "event_id": f"{edition_id or 'unknown'}-{number}",
            "edition_id": edition_id,
            "chapter_number": number,
            "requested_url": chapter.get("sourceUrl"),
            "ok": 1 if chapter.get("ok") else 0,
            "http_status": chapter.get("httpStatus"),
            "sha256": chapter.get("sha256"),
            "bytes": chapter.get("bytes"),
            "attempts": chapter.get("attempts"),
            "error": chapter.get("error"),
            "retrieved_at": chapter.get("retrievedAt"),
        })

    return sorted(result, key=lambda item: item["event_id"])


# (table name, column order, row-building function) -- column order is the
# CSV header and the SQLite column order, both taken directly from
# SCHEMA.md's own table so either can be checked against it by eye.
TABLE_COLUMNS = {
    "ors_edition": [
        "edition_id", "edition_year", "index_url", "index_sha256", "index_bytes",
        "retrieved_at", "chapter_count",
    ],
    "ors_volume": ["volume_id", "edition_id", "volume_number", "first_chapter", "last_chapter"],
    "ors_title": ["title_id", "edition_id", "title_number", "title_name"],
    "ors_chapter": [
        "chapter_id", "edition_id", "title_id", "volume_id", "chapter_number",
        "chapter_sort_key", "chapter_name", "source_url", "source_format",
        "source_sha256", "source_bytes", "retrieved_at",
    ],
    "ors_subdivision": [
        "subdivision_id", "chapter_id", "heading_text", "ordinal",
        "char_offset_start", "char_offset_end",
    ],
    "ors_section": [
        "section_id", "chapter_id", "subdivision_id", "section_number",
        "section_sort_key", "catchline", "body_text", "status", "renumbered_to",
        "ordinal", "char_offset_start", "char_offset_end",
    ],
    "ors_section_note": [
        "note_id", "section_id", "note_kind", "note_text", "ordinal",
        "char_offset_start", "char_offset_end",
    ],
    "ors_source_credit": [
        "credit_id", "section_id", "ordinal", "session_year", "session_law_chapter",
        "session_law_section", "special_session", "action", "raw_credit",
    ],
    "ors_chapter_pending_change": [
        "pending_change_id", "chapter_id", "ordinal", "session_year", "session_law_chapter",
        "change_kind", "notice_text", "char_offset_start", "char_offset_end",
    ],
    "ors_cross_reference": [
        "reference_id", "from_section_id", "to_section_number", "to_section_id",
        "reference_kind", "ordinal", "char_offset_start", "char_offset_end",
    ],
    "ors_acquisition_event": [
        "event_id", "edition_id", "chapter_number", "requested_url", "ok",
        "http_status", "sha256", "bytes", "attempts", "error", "retrieved_at",
    ],
}


def build_tables(rows, roster, acquisition):
    """Build every SCHEMA.md table's rows from the three source reports.

    Returns {table_name: [row, ...]}, each row a plain dict keyed exactly
    as `TABLE_COLUMNS[table_name]` lists -- the same dicts feed NDJSON,
    CSV and the SQLite build, so there is exactly one place each column's
    value is computed.
    """
    editions = rows.get("editions", [])
    edition_id = editions[0]["editionId"] if len(editions) == 1 else None

    return {
        "ors_edition": build_edition_rows(rows, roster),
        "ors_volume": build_volume_rows(edition_id, roster) if edition_id else [],
        "ors_title": build_title_rows(edition_id, roster) if edition_id else [],
        "ors_chapter": build_chapter_rows(rows, acquisition),
        "ors_subdivision": build_subdivision_rows(rows),
        "ors_section": build_section_rows(rows),
        "ors_section_note": build_section_note_rows(rows),
        "ors_source_credit": build_source_credit_rows(rows),
        "ors_chapter_pending_change": build_pending_change_rows(rows),
        "ors_cross_reference": build_cross_reference_rows(rows),
        "ors_acquisition_event": build_acquisition_event_rows(rows, roster, acquisition),
    }


def write_ndjson(table_name, table_rows, out_dir):
    path = out_dir / f"{table_name}.ndjson"
    with path.open("w") as handle:
        for row in table_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def write_csv(table_name, table_rows, out_dir):
    columns = TABLE_COLUMNS[table_name]
    path = out_dir / f"{table_name}.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in table_rows:
            writer.writerow(row)
    return path


# INTEGER columns, everything else is TEXT -- SQLite is dynamically typed
# regardless, but declaring these lets a real integer round-trip through
# the CSV's text representation instead of staying a string.
INTEGER_COLUMNS = {
    "edition_year", "index_bytes", "chapter_count", "volume_number",
    "source_bytes", "ordinal", "char_offset_start", "char_offset_end",
    "session_year", "session_law_chapter", "special_session", "http_status",
    "bytes", "attempts", "ok",
}


def build_sqlite(csv_paths, sqlite_path):
    """Build the SQLite database by reading back the CSVs just written --
    SCHEMA.md calls the CSVs, not the in-memory rows, the source of the
    database, so a rebuild from a set of CSV files alone (without rerunning
    the whole pipeline) produces the identical database.
    """
    if sqlite_path.exists():
        sqlite_path.unlink()
    connection = sqlite3.connect(sqlite_path)
    try:
        for table_name, csv_path in csv_paths.items():
            columns = TABLE_COLUMNS[table_name]
            column_defs = ", ".join(
                f'"{column}" {"INTEGER" if column in INTEGER_COLUMNS else "TEXT"}'
                for column in columns
            )
            connection.execute(f'CREATE TABLE "{table_name}" ({column_defs})')
            placeholders = ", ".join("?" for _ in columns)
            with csv_path.open(newline="") as handle:
                reader = csv.DictReader(handle)
                values = [
                    tuple(row[column] if row[column] != "" else None for column in columns)
                    for row in reader
                ]
            if values:
                connection.executemany(
                    f'INSERT INTO "{table_name}" VALUES ({placeholders})', values
                )
        connection.commit()
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", required=True, help="parse_ors_chapter.py's --rows output")
    parser.add_argument("--roster", required=True, help="acquire_ors_roster.py's --report output")
    parser.add_argument(
        "--acquisition", required=True, help="acquire_ors_chapters.py's --report output"
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--report", help="where to write the summary report JSON")
    args = parser.parse_args(argv)

    rows = json.loads(Path(args.rows).read_text())
    roster = json.loads(Path(args.roster).read_text())
    acquisition = json.loads(Path(args.acquisition).read_text())

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tables = build_tables(rows, roster, acquisition)

    csv_paths = {}
    for table_name, table_rows in tables.items():
        write_ndjson(table_name, table_rows, out_dir)
        csv_paths[table_name] = write_csv(table_name, table_rows, out_dir)

    sqlite_path = out_dir / "ors.sqlite"
    build_sqlite(csv_paths, sqlite_path)

    report = {
        "valid": True,
        "outDir": str(out_dir),
        "sqlitePath": str(sqlite_path),
        "rowCounts": {name: len(table_rows) for name, table_rows in tables.items()},
    }
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
