# ORS Table — incremental delivery plan

This effort is built in small, separately reviewable increments rather than one
large drop. Each increment lands working, tested code and leaves the pipeline in
a runnable state. The next increment starts from measured evidence produced by
the previous one, not from assumptions.

## Increment 1 — foundation (this increment)

- Effort charter and non-interference rule with the amendment parser.
- Relational schema version 1.
- Volume and title discovery from the published `ORS_TitlesChapters.pdf`, and
  chapter acquisition with pinned provenance, validated against the published
  chapter ranges.
- Markup structure probe.
- Offline unit tests plus a loopback end-to-end acquisition test.
- A CI workflow scoped to `ors/**`.

**Exit evidence:** a CI run prints the edition year, the published chapter
roster and a structural fingerprint of the sample chapters. The measurements
taken so far are recorded in [FINDINGS.md](FINDINGS.md); chapter structure is
settled, index discovery is not.

## Increment 1b — chapter roster by verified enumeration

No published document enumerates ORS chapters, so chapters are currently named
explicitly by the fixed development sample and checked against the published
title ranges. A whole-edition build needs a real roster.

- Walk each published title range, fetch each candidate chapter document, and
  record a 200 with its digest as a chapter and a 404 as an absence. Every
  chapter is then backed by a retrieved document and every gap by a recorded
  response, which is verification rather than guessing.
- Lettered chapters are expressed by the ranges themselves (`chs 284-285C`,
  `chs 286A-289`), so enumeration can follow the printed span rather than
  guessing suffixes.
- This is a whole-edition operation of several hundred requests, so it runs on
  manual dispatch, not on every CI run.

## Increment 2 — chapter parsing into `ors_section` (done)

The segmentation rule is now settled by measurement rather than assumption.
Per [FINDINGS.md](FINDINGS.md): the sources are Windows-1252 Word HTML exports
with no semantic markup; each chapter opens with a table of contents that
repeats every section number; and the body headings are distinguished from
that contents list by being bold. Segmentation anchors on bold runs, not on
line position.

- `tools/parse_ors_chapter.py` emitting `ors_edition`, `ors_chapter`,
  `ors_subdivision` and `ors_section` rows with character offsets.
- Edition identity is established from the chapter documents, which print
  `2025` / `EDITION`, and a chapter that states none emits no rows.
- The `SCHEMA.md` referential integrity checks run as a CI gate.
- Section status classification: `operative`, `repealed`, `renumbered`,
  `reserved`, `note_only`, driven by the four credit forms already observed:
  plain enactment, `Repealed by`, `Amended by` and `Formerly`.
- `chapter_name` and `edition_year` read from the chapter document itself,
  which prints both, rather than only from the index.
- Ambiguity is reported as a review queue, never silently resolved.

Three segmentation rules came out of building it, each one a bug the fixture
caught before CI did:

- Two bold headings separated only by a block boundary must not merge into one
  span. When they did, the second section vanished into the first's credit.
- A heading that divides no sections is not a subdivision. The contents list
  repeats the body's headings above unbolded entries, and the edition banner
  looks like one too.
- A subdivision heading **ends** the section above it rather than trailing it.
  Otherwise the heading swallows that section's source credit.

## Increment 3 — notes and source credits

- `ors_section_note` rows, keeping notes out of `body_text`.
- `ors_source_credit` rows parsed from bracketed legislative history.
  Increment 2 already separates the trailing credit from the statutory text
  and keeps it as `sourceCreditRaw`, so this increment parses that string into
  rows rather than having to find it.
- Repealed and renumbered sections. The stubs are printed unbolded, so bold
  anchoring does not reach them: chapter 646A alone shows 138 stubs that
  produced no rows, and every section on the first clean run came back
  `operative` as a result. These need their own anchoring rule.
- This is the table that joins to the amendment parser's `(year, chapter)`
  output. The join is data-only; neither program imports the other.

## Increment 4 — cross references and the relational build

- `ors_cross_reference` rows, with unresolved citations preserved rather than
  dropped.
- CSV emission per table and a SQLite build from the CSVs.
- The referential integrity checks listed in `SCHEMA.md` become a CI gate.

## Increment 5 — gold rows and a quality gate

- A small independently reviewed corpus of chapters with expected section rows,
  established from the authoritative source and never from parser output.
- Precision and recall over `(chapter, section_number)` pairs, plus exact-match
  rates for catchline and status.
- Thresholds set only after a first measurement, so they describe the parser
  rather than flatter it.

## Increment 6 — edition-over-edition rebuild and pending changes

- Rebuild against a new edition without destroying the previous one.
- Section-level diffing between adjacent editions.
- Reconciliation of that diff against the amendment parser's output for the
  intervening sessions: an ORS section whose text changed should correspond to a
  session law the amendment parser reports as amending it.
- An `ors_chapter_pending_change` table. Chapter documents print a notice
  naming the session that has already changed them and the Oregon Laws
  chapters involved — the published 2025 edition already advertises 2026
  changes — which is a printed join to the amendment parser's output.

## Working method

Increments 2 through 4 are developed against the fixed sample in
`sample/chapters.json`, not the whole statute book. The full edition is acquired
only through the workflow's `whole-edition` dispatch scope, and only once the
parsing rules are stable, so routine iteration costs a handful of requests
rather than several hundred.

## Standing rules

1. Do not modify `analyze/`, `tools/`, `gold/`, `operations/`, `validation/` or
   `fixtures/`.
2. Do not weaken a reviewed expectation to make a gate pass.
3. Every acquired byte stream keeps its URL, digest and byte count.
4. Standard library only, so CI needs no dependency installation.
