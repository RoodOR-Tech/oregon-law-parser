# Portable Python pipeline

Python 3.10+ is the only required runtime. SQLite is in the standard library;
PDF parsing uses pdfplumber. The existing Haskell/Tika implementation and its
certification workflows remain available for historical comparison. They are
not invoked by this CLI. The new parser does not inherit their certification.

## Install and run

```sh
python -m pip install -e ".[test,parquet]"
python -m parser.cli run --year 2023 --output ./dist/ors_data.db
```

The run discovers the advertised edition, acquires archived ORS chapter PDFs
or current chapter HTML, then acquires the selected year's regular-session
laws. Full discovery makes approximately two thousand requests and can take
considerable time. Progress is written to stderr. The five requested tables,
source hashes, styled amendment tokens and review diagnostics are published
as one SQLite database. No amendment is automatically applied to an edition.

A smaller **selected-source** run uses the same pipeline:

```sh
python -m parser.cli run --year 2023 --chapters 1 --session-limit 2 --output dist/sample.db
```

Generate Parquet alongside SQLite with `--parquet-dir dist/parquet`. This
requires the `parquet` extra. No DuckDB extension download is required.

Every successful run writes `*.manifest.json` and `*.report.json` beside the
database. Sources are stored under `.ors-cache/objects/<sha256>`, with URL
records under `.ors-cache/urls/`. Cache hits are hash-checked, downloads are
atomic, transient HTTP errors retry, and 404s are recorded as confirmed
absences. Use `--refresh` for deliberate reacquisition; source-hash mismatch
in a pinned manifest still fails. `--offline` refuses uncached network reads.

```sh
python -m parser.cli run --year 2023 --manifest dist/sample.manifest.json --offline --output dist/replay.db
python -m pytest -q
```

To run without any network at all, use the clearly synthetic test fixtures:

```sh
python -m parser.cli run --year 2023 --manifest tests/fixtures/manifest.json --output dist/example.db
```

## Source manifests and supplements

A manifest is also the interface for alternate indexes, local source archives,
and special-session supplements. Local paths resolve relative to the manifest.
Published headers must match `edition_year` and `session_year`; filenames are
locators, not edition evidence. Missing or contradictory identity is an error.

```json
{
  "schema_version": 1,
  "edition_year": 2023,
  "scope": "selected",
  "documents": [
    {"kind": "chapter", "chapter_number": "161", "path": "sources/chapter.html"},
    {"kind": "session", "session_year": 2024, "special_session": 1,
     "path": "sources/supplement.pdf"}
  ]
}
```

Use `source_url` instead of `path` for remote sources and `sha256` to pin bytes.
PDF records default to two columns; explicitly set `columns: 1` for a
single-column publication. Image-only PDFs require OCR and fail explicitly.
Special-session identity must be supplied by the source manifest because some
published headers state only the year. Special sessions have distinct action
IDs even when chapter numbers coincide with a regular session.

Edition rows do not imply a single legal effective date. `effective_date`
remains NULL unless explicitly supplied. Notes retain advertised supplements;
later laws remain separate. Historical volume numbers remain NULL where the
archive provides no verified edition-specific volume roster.

## Tables

| Table | Columns |
|---|---|
| `editions` | `edition_year`, `effective_date`, `source_url`, `notes` |
| `chapters` | `chapter_number`, `title`, `volume_number`, `edition_year` |
| `sections` | `ors_section`, `chapter_number`, `catchline`, `content_text`, `edition_year` |
| `amendments` | `id`, `bill_number`, `session_year`, `affected_ors_section`, `action_type`, `raw_diff_text` |
| `pending_changes` | `id`, `target_section`, `enacting_measure`, `effective_date`, `note_text` |

Chapter and section numbers are TEXT, including lettered chapters and leading
fractional zeros. Section/chapter keys include the edition. Each run atomically
rebuilds one database; it does not append to an existing database. Failed parsing
preserves an existing SQLite output.

Additional tables preserve facts that the compact schema cannot express:

- `sources`, `chapter_sources`, `amendment_sources`: byte hashes and publication
  identity, including session chapter, clause and special-session ordinal.
- `amendment_tokens`: lexical tokens with `KEEP`, `ADD`, `DELETE` or `MARKER`,
  ordinal and offsets into `raw_diff_text`. Bracket delimiters are markers;
  deletion overrides bold/underline styling inside a bracket. PDF running
  headers and page numbers are removed; columns are read separately. Line-end
  hyphenation and whitespace are normalized. Original bytes remain cached.
- `section_notes`: source credits and editorial notes separated from statute
  text. Strict closed-bracket notes do not consume following statutory text.
- `pending_change_sources`: edition/chapter provenance for every notice.
- `diagnostics`: uncodified or unsupported operative targets requiring review.
- `build_metadata`: canonical manifest, parser version, scope and review flag.

`ADD` rows can have a NULL `affected_ors_section`: the act's section has not
necessarily received an ORS number. A receiving ORS chapter/series is not
invented as a new section identifier. General chapter notices likewise have
NULL `target_section`. Explicit effective dates are parsed; operative dates
and other dates remain in the original note without being conflated.

## Query

```python
import sqlite3

with sqlite3.connect("dist/ors_data.db") as db:
    rows = db.execute("""
        SELECT ors_section, catchline, content_text
        FROM sections WHERE edition_year = ? AND chapter_number = ?
        ORDER BY ors_section
    """, (2023, "161")).fetchall()
    changes = db.execute("""
        SELECT a.bill_number, a.action_type, s.session_law_chapter,
               s.session_law_section, a.raw_diff_text
        FROM amendments a JOIN amendment_sources s ON s.amendment_id = a.id
        WHERE a.affected_ors_section = ? ORDER BY a.session_year, a.id
    """, ("161.005",)).fetchall()
    review = db.execute("SELECT source_url, clause, reason FROM diagnostics").fetchall()
```

## Validation scope and limitations

Offline CI covers the existing ORS/review tests and the new cache, edition,
note-boundary, styled-token, relational integrity and export tests on Windows
and Linux. Bundled real session-law PDFs verify direct ORS targets and that
citations in amendments to earlier acts are not misfiled as direct amendments.

Discovery uses the public archive's edition labels and document-library path,
the linked table of titles, and comparative section table. The archive list API
is not anonymously readable. Numeric candidates and consecutive lettered
families are therefore probed, with 404s distinguished from network failure.
Historical discovery uses today's largest chapter endpoint; it is not an
independently certified historical roster. The report labels this scope
`discovered`, not certified-complete.

The initial Python session parser handles direct amendments/repeals and added
provisions, including explicit act-section lists and ranges. Repeal ranges and
unrecognized addition references require review, as do amendments to uncodified acts. Consult `diagnostics` and
`review_required`; successful extraction is not certification that every
legislative action or font convention is understood. Publication layouts beyond
the tested layouts may fail and should receive explicit fixtures before use.

Existing reviewed previews and the richer `ors_*` schema remain available via
the original tools in `ors/tools`; the portable tables are a new compact export,
not a migration that removes those tables or rewrites frozen review material.
