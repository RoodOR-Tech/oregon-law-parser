"""Normalized SQLite publication and optional typed Parquet export."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from contextlib import closing

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE editions(edition_year INTEGER PRIMARY KEY, effective_date TEXT, source_url TEXT NOT NULL, notes TEXT);
CREATE TABLE chapters(chapter_number TEXT NOT NULL, title TEXT, volume_number INTEGER, edition_year INTEGER NOT NULL REFERENCES editions, PRIMARY KEY(edition_year,chapter_number));
CREATE TABLE sections(ors_section TEXT NOT NULL, chapter_number TEXT NOT NULL, catchline TEXT, content_text TEXT, edition_year INTEGER NOT NULL, PRIMARY KEY(edition_year,ors_section), FOREIGN KEY(edition_year,chapter_number) REFERENCES chapters(edition_year,chapter_number));
CREATE TABLE amendments(id TEXT PRIMARY KEY, bill_number TEXT NOT NULL, session_year INTEGER NOT NULL, affected_ors_section TEXT, action_type TEXT NOT NULL CHECK(action_type IN ('AMEND','REPEAL','ADD')), raw_diff_text TEXT NOT NULL);
CREATE TABLE pending_changes(id TEXT PRIMARY KEY, target_section TEXT, enacting_measure TEXT, effective_date TEXT, note_text TEXT NOT NULL);
CREATE TABLE sources(source_url TEXT PRIMARY KEY, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL);
CREATE TABLE chapter_sources(edition_year INTEGER, chapter_number TEXT, source_url TEXT REFERENCES sources, PRIMARY KEY(edition_year,chapter_number), FOREIGN KEY(edition_year,chapter_number) REFERENCES chapters(edition_year,chapter_number));
CREATE TABLE amendment_sources(amendment_id TEXT PRIMARY KEY REFERENCES amendments, source_url TEXT REFERENCES sources, session_law_chapter INTEGER, session_law_section TEXT, special_session INTEGER NOT NULL);
CREATE TABLE amendment_tokens(amendment_id TEXT REFERENCES amendments, ordinal INTEGER, operation TEXT CHECK(operation IN ('KEEP','ADD','DELETE','MARKER')), text TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, PRIMARY KEY(amendment_id,ordinal));
CREATE TABLE section_notes(id TEXT PRIMARY KEY, edition_year INTEGER, ors_section TEXT, note_kind TEXT, note_text TEXT NOT NULL, FOREIGN KEY(edition_year,ors_section) REFERENCES sections(edition_year,ors_section));
CREATE TABLE chapter_notes(id TEXT PRIMARY KEY, edition_year INTEGER, chapter_number TEXT, note_text TEXT NOT NULL, FOREIGN KEY(edition_year,chapter_number) REFERENCES chapters(edition_year,chapter_number));
CREATE TABLE section_versions(edition_year INTEGER, ors_section TEXT, version_ordinal INTEGER, catchline TEXT, content_text TEXT, status TEXT, source_credit TEXT, publication_notes TEXT, PRIMARY KEY(edition_year,ors_section,version_ordinal), FOREIGN KEY(edition_year,ors_section) REFERENCES sections(edition_year,ors_section));
CREATE TABLE pending_change_sources(pending_change_id TEXT PRIMARY KEY REFERENCES pending_changes, edition_year INTEGER, chapter_number TEXT, source_url TEXT REFERENCES sources, FOREIGN KEY(edition_year,chapter_number) REFERENCES chapters(edition_year,chapter_number));
CREATE TABLE diagnostics(id TEXT PRIMARY KEY, source_url TEXT REFERENCES sources, clause TEXT, reason TEXT, text TEXT);
CREATE TABLE amendment_context(amendment_id TEXT PRIMARY KEY REFERENCES amendments, condition_text TEXT, operative_text TEXT NOT NULL);
CREATE TABLE diagnostic_reviews(diagnostic_id TEXT PRIMARY KEY REFERENCES diagnostics, category TEXT NOT NULL, disposition TEXT NOT NULL, explanation TEXT NOT NULL);
CREATE TABLE build_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX amendments_by_target ON amendments(affected_ors_section,session_year);
CREATE INDEX pending_by_target ON pending_changes(target_section,effective_date);
"""


def write_sqlite(path, tables):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    os.close(fd)
    try:
        with closing(sqlite3.connect(name)) as db, db:
            db.executescript(SCHEMA)
            for table, rows in tables.items():
                if not rows:
                    continue
                columns = list(rows[0])
                placeholders = ",".join("?" for _ in columns)
                db.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                               [tuple(row[c] for c in columns) for row in sorted(rows, key=lambda r: json.dumps(r, sort_keys=True))])
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("foreign-key integrity check failed")
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def export_parquet(database, directory):
    import duckdb
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Use sqlite3 to read rather than DuckDB's network-installed sqlite extension.
    with closing(sqlite3.connect(database)) as db, duckdb.connect() as target, tempfile.TemporaryDirectory(dir=directory) as staging:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            info = db.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = ",".join(f'"{c[1]}" {"BIGINT" if c[2] == "INTEGER" else "VARCHAR"}' for c in info)
            target.execute(f'CREATE TABLE "{table}" ({columns})')
            ordering = ','.join('"'+c[1]+'"' for c in sorted(info, key=lambda c: c[5]) if c[5])
            ordering = ordering or ','.join(str(i+1) for i in range(len(info)))
            cursor = db.execute(f'SELECT * FROM "{table}" ORDER BY {ordering}')
            # Stream through typed NDJSON. Row-by-row DuckDB inserts are too
            # slow for a statewide token table; no extension or Arrow required.
            transfer = Path(staging)/'rows.ndjson'
            count = 0
            with transfer.open('w',encoding='utf-8',newline='\n') as stream:
                while rows := cursor.fetchmany(10000):
                    count += len(rows)
                    for row in rows:
                        stream.write(json.dumps(dict(zip([c[1] for c in info], row)),ensure_ascii=False)+'\n')
            if count:
                types = ','.join("'"+c[1]+"': '"+('BIGINT' if c[2]=='INTEGER' else 'VARCHAR')+"'" for c in info)
                target.execute(f'INSERT INTO "{table}" SELECT * FROM read_json(?, columns={{{types}}}, format=\'newline_delimited\', maximum_object_size=67108864)', [str(transfer)])
            output = str(Path(staging) / (table + ".parquet")).replace("'", "''")
            target.execute(f'COPY "{table}" TO \'{output}\' (FORMAT PARQUET)')
            os.replace(Path(staging)/(table+'.parquet'), directory/(table+'.parquet'))
            target.execute(f'DROP TABLE "{table}"')
