#!/usr/bin/env python3
"""Tests for joining the roster, acquisition and parsed-rows reports into
SCHEMA.md's own relational tables (NDJSON, CSV, SQLite).
"""
import csv
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import build_ors_relational as build  # noqa: E402


def sample_rows():
    return {
        "editions": [{"editionId": "2025", "editionYear": 2025, "chapterCount": 1}],
        "chapters": [{
            "chapterId": "2025-1",
            "editionId": "2025",
            "chapterNumber": "1",
            "chapterSortKey": "000001 ",
            "chapterName": "Courts and Judicial Officers Generally",
            "titleNumber": "1",
            "volumeNumber": 1,
            "sourceUrl": "https://example.test/ors001.html",
            "sourceSha256": "a" * 64,
            "sourceBytes": 1234,
            "sectionCount": 1,
        }],
        "subdivisions": [{
            "subdivisionId": "2025-1-sd0001",
            "chapterId": "2025-1",
            "headingText": "(Definitions)",
            "ordinal": 1,
            "charOffsetStart": 10,
            "charOffsetEnd": 20,
        }],
        "sections": [{
            "sectionId": "2025-1.002",
            "chapterId": "2025-1",
            "subdivisionId": None,
            "sectionNumber": "1.002",
            "sectionSortKey": "000001 .002",
            "catchline": "Some catchline.",
            "bodyText": "Some statutory text.",
            "status": "operative",
            "renumberedTo": None,
            "ordinal": 1,
            "charOffsetStart": 100,
            "charOffsetEnd": 200,
        }],
        "sectionNotes": [{
            "noteId": "2025-1.002-n001",
            "sectionId": "2025-1.002",
            "noteKind": "editorial_note",
            "noteText": "Note: Sections 3 and 4, chapter 88, Oregon Laws 2025, provide:",
            "ordinal": 1,
            "charOffsetStart": 150,
            "charOffsetEnd": 190,
        }],
        "sourceCredits": [{
            "creditId": "2025-1.002-c001",
            "sectionId": "2025-1.002",
            "ordinal": 1,
            "sessionYear": 2025,
            "sessionLawChapter": 256,
            "sessionLawSection": "6",
            "specialSession": None,
            "action": "amended",
            "rawCredit": "2025 c.256 §6",
        }],
        "crossReferences": [{
            "referenceId": "2025-1.002-x0001",
            "fromSectionId": "2025-1.002",
            "toSectionNumber": "90.100",
            "toSectionId": None,
            "referenceKind": "section",
            "ordinal": 1,
            "charOffsetStart": 105,
            "charOffsetEnd": 111,
        }],
        "pendingChanges": [{
            "pendingChangeId": "2025-1-p001",
            "chapterId": "2025-1",
            "ordinal": 1,
            "sessionYear": 2026,
            "sessionLawChapter": 57,
            "changeKind": "new_series_section",
            "noticeText": "New sections of law were added ... 2026 Session Laws 0057",
            "charOffsetStart": 5,
            "charOffsetEnd": 9,
        }],
    }


def sample_roster():
    return {
        "rosterUrl": "https://example.test/ORS_TitlesChapters.pdf",
        "rosterSha256": "b" * 64,
        "rosterBytes": 5678,
        "rosterHttpStatus": 200,
        "rosterAttempts": 1,
        "retrievedAt": "2026-01-01T00:00:00Z",
        "volumes": [{"volumeNumber": 1, "firstChapter": "1", "lastChapter": "10"}],
        "titles": [{
            "titleNumber": "1",
            "titleName": "Courts of Record; Court Officers; Juries",
            "volumeNumber": 1,
            "firstChapter": "1",
            "lastChapter": "10",
        }],
    }


def sample_acquisition():
    return {
        "chapters": [{
            "chapterNumber": "1",
            "sourceUrl": "https://example.test/ors001.html",
            "sourceFormat": "html",
            "ok": True,
            "httpStatus": 200,
            "sha256": "a" * 64,
            "bytes": 1234,
            "attempts": 1,
            "retrievedAt": "2026-01-01T00:05:00Z",
        }],
    }


class EditionRowTest(unittest.TestCase):
    def test_edition_joins_roster_provenance_onto_rows_own_edition(self):
        rows = build.build_edition_rows(sample_rows(), sample_roster())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["edition_id"], "2025")
        self.assertEqual(row["edition_year"], 2025)
        self.assertEqual(row["index_url"], "https://example.test/ORS_TitlesChapters.pdf")
        self.assertEqual(row["index_sha256"], "b" * 64)
        self.assertEqual(row["chapter_count"], 1)


class VolumeAndTitleRowTest(unittest.TestCase):
    def test_volume_id_is_deterministic_and_zero_padded(self):
        rows = build.build_volume_rows("2025", sample_roster())
        self.assertEqual(rows[0]["volume_id"], "2025-v01")
        self.assertEqual(rows[0]["first_chapter"], "1")

    def test_title_id_is_deterministic(self):
        rows = build.build_title_rows("2025", sample_roster())
        self.assertEqual(rows[0]["title_id"], "2025-t1")
        self.assertEqual(rows[0]["title_name"], "Courts of Record; Court Officers; Juries")


class ChapterRowTest(unittest.TestCase):
    def test_chapter_gets_title_and_volume_foreign_keys(self):
        rows = build.build_chapter_rows(sample_rows(), sample_acquisition())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["chapter_id"], "2025-1")
        self.assertEqual(row["title_id"], "2025-t1")
        self.assertEqual(row["volume_id"], "2025-v01")

    def test_chapter_joins_source_format_and_retrieved_at_from_acquisition(self):
        row = build.build_chapter_rows(sample_rows(), sample_acquisition())[0]
        self.assertEqual(row["source_format"], "html")
        self.assertEqual(row["retrieved_at"], "2026-01-01T00:05:00Z")

    def test_a_chapter_missing_from_acquisition_gets_null_join_fields(self):
        rows_data = sample_rows()
        row = build.build_chapter_rows(rows_data, {"chapters": []})[0]
        self.assertIsNone(row["source_format"])
        self.assertIsNone(row["retrieved_at"])


class SimpleTableRowTest(unittest.TestCase):
    """The tables that only rename camelCase keys to snake_case."""

    def test_subdivision_rows(self):
        row = build.build_subdivision_rows(sample_rows())[0]
        self.assertEqual(row["subdivision_id"], "2025-1-sd0001")
        self.assertEqual(row["heading_text"], "(Definitions)")

    def test_section_rows_drop_source_credit_raw(self):
        row = build.build_section_rows(sample_rows())[0]
        self.assertEqual(row["section_id"], "2025-1.002")
        self.assertEqual(row["body_text"], "Some statutory text.")
        self.assertNotIn("source_credit_raw", row)
        self.assertNotIn("sourceCreditRaw", row)

    def test_section_note_rows(self):
        row = build.build_section_note_rows(sample_rows())[0]
        self.assertEqual(row["note_id"], "2025-1.002-n001")
        self.assertEqual(row["note_kind"], "editorial_note")

    def test_source_credit_rows(self):
        row = build.build_source_credit_rows(sample_rows())[0]
        self.assertEqual(row["credit_id"], "2025-1.002-c001")
        self.assertEqual(row["session_law_chapter"], 256)

    def test_cross_reference_rows(self):
        row = build.build_cross_reference_rows(sample_rows())[0]
        self.assertEqual(row["reference_id"], "2025-1.002-x0001")
        self.assertIsNone(row["to_section_id"])

    def test_pending_change_rows(self):
        row = build.build_pending_change_rows(sample_rows())[0]
        self.assertEqual(row["pending_change_id"], "2025-1-p001")
        self.assertEqual(row["chapter_id"], "2025-1")
        self.assertEqual(row["session_law_chapter"], 57)
        self.assertEqual(row["change_kind"], "new_series_section")

    def test_a_pending_change_naming_no_specific_chapter_keeps_it_null(self):
        rows = sample_rows()
        rows["pendingChanges"][0]["sessionLawChapter"] = None
        rows["pendingChanges"][0]["changeKind"] = "amended_or_repealed_elsewhere"
        row = build.build_pending_change_rows(rows)[0]
        self.assertIsNone(row["session_law_chapter"])


class AcquisitionEventRowTest(unittest.TestCase):
    def test_the_index_fetch_is_its_own_event(self):
        rows = build.build_acquisition_event_rows(
            sample_rows(), sample_roster(), sample_acquisition()
        )
        index_events = [r for r in rows if r["chapter_number"] is None]
        self.assertEqual(len(index_events), 1)
        event = index_events[0]
        self.assertEqual(event["edition_id"], "2025")
        self.assertEqual(event["ok"], 1)
        self.assertEqual(event["sha256"], "b" * 64)

    def test_a_chapter_fetch_uses_its_own_parsed_edition(self):
        rows = build.build_acquisition_event_rows(
            sample_rows(), sample_roster(), sample_acquisition()
        )
        chapter_events = [r for r in rows if r["chapter_number"] == "1"]
        self.assertEqual(len(chapter_events), 1)
        self.assertEqual(chapter_events[0]["edition_id"], "2025")
        self.assertEqual(chapter_events[0]["ok"], 1)

    def test_a_failed_fetch_falls_back_to_the_builds_one_edition(self):
        acquisition = {
            "chapters": [{
                "chapterNumber": "999",
                "sourceUrl": "https://example.test/ors999.html",
                "ok": False,
                "httpStatus": 404,
                "attempts": 1,
                "error": "not found",
                "retrievedAt": "2026-01-01T00:06:00Z",
            }],
        }
        rows = build.build_acquisition_event_rows(sample_rows(), sample_roster(), acquisition)
        failed = next(r for r in rows if r["chapter_number"] == "999")
        # 999 never became a parsed chapter, so it has no edition of its
        # own -- it falls back to the one edition this build parsed.
        self.assertEqual(failed["edition_id"], "2025")
        self.assertEqual(failed["ok"], 0)
        self.assertEqual(failed["error"], "not found")


class BuildTablesTest(unittest.TestCase):
    def test_every_schema_table_is_present(self):
        tables = build.build_tables(sample_rows(), sample_roster(), sample_acquisition())
        self.assertEqual(set(tables), set(build.TABLE_COLUMNS))

    def test_row_dicts_use_exactly_the_declared_columns(self):
        tables = build.build_tables(sample_rows(), sample_roster(), sample_acquisition())
        for table_name, table_rows in tables.items():
            expected = set(build.TABLE_COLUMNS[table_name])
            for row in table_rows:
                self.assertEqual(set(row), expected, table_name)


class CsvAndNdjsonTest(unittest.TestCase):
    def test_csv_header_matches_declared_columns_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            rows = build.build_section_rows(sample_rows())
            path = build.write_csv("ors_section", rows, out_dir)
            with path.open(newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, build.TABLE_COLUMNS["ors_section"])
                written = list(reader)
            self.assertEqual(written[0]["section_id"], "2025-1.002")

    def test_ndjson_round_trips_one_object_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            rows = build.build_cross_reference_rows(sample_rows())
            path = build.write_ndjson("ors_cross_reference", rows, out_dir)
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["reference_id"], "2025-1.002-x0001")

    def test_a_null_value_round_trips_as_empty_csv_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            rows = build.build_cross_reference_rows(sample_rows())
            path = build.write_csv("ors_cross_reference", rows, out_dir)
            with path.open(newline="") as handle:
                written = list(csv.DictReader(handle))
            self.assertEqual(written[0]["to_section_id"], "")


class SqliteBuildTest(unittest.TestCase):
    def test_the_database_has_every_table_with_the_right_row_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            tables = build.build_tables(sample_rows(), sample_roster(), sample_acquisition())
            csv_paths = {
                name: build.write_csv(name, table_rows, out_dir)
                for name, table_rows in tables.items()
            }
            sqlite_path = out_dir / "ors.sqlite"
            build.build_sqlite(csv_paths, sqlite_path)

            connection = sqlite3.connect(sqlite_path)
            try:
                for table_name, table_rows in tables.items():
                    count = connection.execute(
                        f'SELECT COUNT(*) FROM "{table_name}"'
                    ).fetchone()[0]
                    self.assertEqual(count, len(table_rows), table_name)
            finally:
                connection.close()

    def test_integer_columns_come_back_as_integers_not_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            tables = build.build_tables(sample_rows(), sample_roster(), sample_acquisition())
            csv_paths = {
                name: build.write_csv(name, table_rows, out_dir)
                for name, table_rows in tables.items()
            }
            sqlite_path = out_dir / "ors.sqlite"
            build.build_sqlite(csv_paths, sqlite_path)

            connection = sqlite3.connect(sqlite_path)
            try:
                year = connection.execute(
                    "SELECT edition_year FROM ors_edition"
                ).fetchone()[0]
                self.assertIsInstance(year, int)
            finally:
                connection.close()

    def test_a_null_foreign_key_comes_back_as_sql_null_not_empty_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            tables = build.build_tables(sample_rows(), sample_roster(), sample_acquisition())
            csv_paths = {
                name: build.write_csv(name, table_rows, out_dir)
                for name, table_rows in tables.items()
            }
            sqlite_path = out_dir / "ors.sqlite"
            build.build_sqlite(csv_paths, sqlite_path)

            connection = sqlite3.connect(sqlite_path)
            try:
                value = connection.execute(
                    "SELECT to_section_id FROM ors_cross_reference"
                ).fetchone()[0]
                self.assertIsNone(value)
            finally:
                connection.close()


class MainCliTest(unittest.TestCase):
    def test_main_writes_ndjson_csv_and_sqlite_for_every_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows_path = root / "rows.json"
            roster_path = root / "roster.json"
            acquisition_path = root / "acquisition.json"
            out_dir = root / "out"

            rows_path.write_text(json.dumps(sample_rows()))
            roster_path.write_text(json.dumps(sample_roster()))
            acquisition_path.write_text(json.dumps(sample_acquisition()))

            report_path = root / "report.json"
            exit_code = build.main([
                "--rows", str(rows_path),
                "--roster", str(roster_path),
                "--acquisition", str(acquisition_path),
                "--out-dir", str(out_dir),
                "--report", str(report_path),
            ])
            self.assertEqual(exit_code, 0)

            for table_name in build.TABLE_COLUMNS:
                self.assertTrue((out_dir / f"{table_name}.ndjson").exists())
                self.assertTrue((out_dir / f"{table_name}.csv").exists())
            self.assertTrue((out_dir / "ors.sqlite").exists())

            report = json.loads(report_path.read_text())
            self.assertTrue(report["valid"])
            self.assertEqual(report["rowCounts"]["ors_section"], 1)


if __name__ == "__main__":
    unittest.main()
