# ORS Relational Schema — version 1

The target deliverable is a set of normalized tables covering one published
edition of the Oregon Revised Statutes. Multiple editions coexist in the same
tables, keyed by `edition_id`, so a rebuild after a new session adds rows rather
than destroying the previous edition.

Every table is emitted in three interchangeable forms from the same row data:
newline-delimited JSON (canonical), CSV (one file per table), and a SQLite
database built from the CSVs. The JSON form is canonical because it is the form
diffed and reviewed.

## Conventions

- All identifiers are lowercase `snake_case`.
- Surrogate keys are deterministic strings, not autoincrement integers, so a
  rebuild from the same sources produces byte-identical output.
- Chapter and section numbers are `TEXT`, never numeric: ORS uses lettered
  chapters (`279A`, `279B`, `646A`) and section numbers are dotted pairs whose
  fractional part is significant (`161.005` sorts before `161.067`, and
  `161.100` is not `161.1`).
- Every table that holds parsed text carries a `char_offset_start` /
  `char_offset_end` pair into the normalized chapter text, so any row can be
  traced back to the exact span of the pinned source that produced it.
- Timestamps are ISO 8601 UTC with a trailing `Z`.

## Sort keys

`chapter_sort_key` is `(numeric_part, letter_part)` rendered as a fixed-width
string: chapter `279A` becomes `000279A`, chapter `1` becomes `000001 `. This
makes lexical ordering match legal ordering.

`section_sort_key` is `chapter_sort_key` plus the zero-padded fractional part:
`161.005` becomes `000161 .005`, `161.067` becomes `000161 .067`.

## Tables

### `ors_edition`

One row per published edition of the statute book.

| column | type | notes |
|---|---|---|
| `edition_id` | TEXT PK | e.g. `2025` |
| `edition_year` | INTEGER | e.g. `2025` |
| `index_url` | TEXT | the exact page the chapter roster was read from |
| `index_sha256` | TEXT | digest of that page's bytes |
| `index_bytes` | INTEGER | byte count of that page |
| `retrieved_at` | TEXT | ISO 8601 UTC |
| `chapter_count` | INTEGER | chapters discovered in this edition |

### `ors_volume`

The printed ORS is bound in numbered volumes, each covering a chapter range.
Volume membership is useful for reconciling against the Legislative Counsel
volume update PDFs.

| column | type | notes |
|---|---|---|
| `volume_id` | TEXT PK | `{edition_id}-v{volume_number:02d}` |
| `edition_id` | TEXT FK → `ors_edition` | |
| `volume_number` | INTEGER | |
| `first_chapter` | TEXT | |
| `last_chapter` | TEXT | |

### `ors_title`

ORS titles group chapters by subject (Title 16 "Crimes and Punishments").

| column | type | notes |
|---|---|---|
| `title_id` | TEXT PK | `{edition_id}-t{title_number}` |
| `edition_id` | TEXT FK → `ors_edition` | |
| `title_number` | TEXT | |
| `title_name` | TEXT | |

### `ors_chapter`

| column | type | notes |
|---|---|---|
| `chapter_id` | TEXT PK | `{edition_id}-{chapter_number}` |
| `edition_id` | TEXT FK → `ors_edition` | |
| `title_id` | TEXT FK → `ors_title` | nullable until titles are ingested |
| `volume_id` | TEXT FK → `ors_volume` | nullable until volumes are ingested |
| `chapter_number` | TEXT | `161`, `279A` |
| `chapter_sort_key` | TEXT | see Sort keys |
| `chapter_name` | TEXT | |
| `source_url` | TEXT | pinned |
| `source_format` | TEXT | `html` or `pdf` |
| `source_sha256` | TEXT | pinned |
| `source_bytes` | INTEGER | pinned |
| `retrieved_at` | TEXT | |

### `ors_subdivision`

Chapters are internally divided by centered headings such as `(Definitions)` or
`GENERAL PROVISIONS`. These carry no section number but do carry meaning.

| column | type | notes |
|---|---|---|
| `subdivision_id` | TEXT PK | `{chapter_id}-sd{ordinal:04d}` |
| `chapter_id` | TEXT FK → `ors_chapter` | |
| `heading_text` | TEXT | |
| `ordinal` | INTEGER | position within the chapter |
| `char_offset_start` | INTEGER | |
| `char_offset_end` | INTEGER | |

### `ors_section`

The central table. One row per ORS section as printed, including sections
printed only as a repeal or renumbering stub.

| column | type | notes |
|---|---|---|
| `section_id` | TEXT PK | `{edition_id}-{section_number}` |
| `chapter_id` | TEXT FK → `ors_chapter` | |
| `subdivision_id` | TEXT FK → `ors_subdivision` | nullable |
| `section_number` | TEXT | `161.005` |
| `section_sort_key` | TEXT | see Sort keys |
| `catchline` | TEXT | the leadline, nullable for stubs |
| `body_text` | TEXT | normalized statutory text, notes excluded |
| `status` | TEXT | `operative`, `repealed`, `renumbered`, `reserved`, `note_only` |
| `renumbered_to` | TEXT | nullable; set when `status = renumbered` |
| `ordinal` | INTEGER | position within the chapter |
| `char_offset_start` | INTEGER | |
| `char_offset_end` | INTEGER | |

`status` values are closed and mirror the amendment parser's discipline of
naming states explicitly rather than encoding them as absent data.

### `ors_section_note`

Editorial and legislative notes printed with a section, kept out of `body_text`
so the statutory text stays clean.

| column | type | notes |
|---|---|---|
| `note_id` | TEXT PK | `{section_id}-n{ordinal:03d}` |
| `section_id` | TEXT FK → `ors_section` | |
| `note_kind` | TEXT | `source_credit`, `editorial_note`, `preface_note` |
| `note_text` | TEXT | |
| `ordinal` | INTEGER | |
| `char_offset_start` | INTEGER | |
| `char_offset_end` | INTEGER | |

### `ors_source_credit`

The bracketed legislative history under a section — `[1971 c.743 §1; 1973 c.836
§339]` — parsed into rows. This is the table that joins this effort to the
amendment parser: `(session_year, session_law_chapter)` is exactly the
`(year, chapter)` identity the amendment parser emits.

| column | type | notes |
|---|---|---|
| `credit_id` | TEXT PK | `{section_id}-c{ordinal:03d}` |
| `section_id` | TEXT FK → `ors_section` | |
| `ordinal` | INTEGER | order as printed |
| `session_year` | INTEGER | `1971` |
| `session_law_chapter` | INTEGER | `743` |
| `session_law_section` | TEXT | `1`, `3a`; nullable |
| `special_session` | INTEGER | nullable; `1` when the citation carries an `s.s.` marker, `NULL` otherwise. No numbered special session (e.g. a 2002-style "Second Special Session") has been observed in a printed citation; if one is, this column's meaning will need revisiting rather than silently overloading it with an ordinal. |
| `action` | TEXT | `enacted`, `amended`, `renumbered`, `repealed`, `unspecified` |
| `raw_credit` | TEXT | the exact substring parsed |

`action` defaults to `unspecified` rather than being guessed. The printed credit
does not always state the action, and inventing one would defeat the join.

### `ors_cross_reference`

Section-to-section citations found in statutory text.

| column | type | notes |
|---|---|---|
| `reference_id` | TEXT PK | `{section_id}-x{ordinal:04d}` |
| `from_section_id` | TEXT FK → `ors_section` | |
| `to_section_number` | TEXT | as cited |
| `to_section_id` | TEXT FK → `ors_section` | nullable when unresolved |
| `reference_kind` | TEXT | `section`, `range_start`, `range_end`, `chapter` |
| `ordinal` | INTEGER | |
| `char_offset_start` | INTEGER | |
| `char_offset_end` | INTEGER | |

An unresolved citation keeps `to_section_id` null rather than being dropped:
citations to repealed or never-existing sections are real data.

### `ors_acquisition_event`

The provenance ledger. One row per fetch attempt, successful or not.

| column | type | notes |
|---|---|---|
| `event_id` | TEXT PK | |
| `edition_id` | TEXT FK → `ors_edition` | |
| `chapter_number` | TEXT | nullable for index fetches |
| `requested_url` | TEXT | |
| `ok` | INTEGER | 0/1 |
| `http_status` | INTEGER | nullable |
| `sha256` | TEXT | nullable on failure |
| `bytes` | INTEGER | nullable on failure |
| `attempts` | INTEGER | |
| `error` | TEXT | nullable |
| `retrieved_at` | TEXT | |

## Referential integrity checks

A build is valid only if all of the following hold. These become the quality
gate in CI, in the same spirit as the amendment effort's gold gate:

1. Every `ors_chapter.edition_id` resolves to an `ors_edition`.
2. Every `ors_section.chapter_id` resolves to an `ors_chapter`.
3. Every `ors_section_credit.section_id` and `ors_section_note.section_id`
   resolves to an `ors_section`.
4. `ors_section.section_number` is unique within an edition.
5. Every `ors_section.section_number` begins with its chapter's number, so a
   section is never filed under the wrong chapter.
6. Every chapter discovered in the index produced at least one `ors_section`
   row, or is explicitly recorded as an empty chapter with a reason.
7. Every `ors_chapter` row has a non-null `source_sha256`.

## Deferred to a later schema version

Recorded here so they are not silently forgotten:

- Subsection-level decomposition — `(1)`, `(a)`, `(A)` — as its own table.
- Temporary and uncodified provisions printed as chapter notes without a section
  number.
- Section-level diffing between adjacent editions, which is the natural place to
  reconcile against the amendment parser's output.
