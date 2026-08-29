# ORS Table — incremental delivery plan

This effort is built in small, separately reviewable increments rather than one
large drop. Each increment lands working, tested code and leaves the pipeline in
a runnable state. The next increment starts from measured evidence produced by
the previous one, not from assumptions.

## Increment 1 — foundation (this increment)

- Effort charter and non-interference rule with the amendment parser.
- Relational schema version 1.
- Chapter discovery and acquisition with pinned provenance.
- Markup structure probe.
- Offline unit tests plus a loopback end-to-end acquisition test.
- A CI workflow scoped to `ors/**`.

**Exit evidence:** the CI run prints the real edition year, the full published
chapter roster and a structural fingerprint of sample chapters. That output is
the ground truth the parser is written against.

## Increment 2 — chapter parsing into `ors_section`

Blocked on increment 1's probe output, deliberately. The published markup
determines the segmentation rule, and the probe already shows the rule cannot be
"a line starting with a section number" — wrapped citation lines such as
`161.055, unless the context requires otherwise:` open that way too.

- `tools/parse_ors_chapter.py` emitting `ors_chapter`, `ors_subdivision` and
  `ors_section` rows with character offsets.
- Section status classification: `operative`, `repealed`, `renumbered`,
  `reserved`, `note_only`.
- Ambiguity is reported as a review queue, never silently resolved.

## Increment 3 — notes and source credits

- `ors_section_note` rows, keeping notes out of `body_text`.
- `ors_source_credit` rows parsed from bracketed legislative history.
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

## Increment 6 — edition-over-edition rebuild

- Rebuild against a new edition without destroying the previous one.
- Section-level diffing between adjacent editions.
- Reconciliation of that diff against the amendment parser's output for the
  intervening sessions: an ORS section whose text changed should correspond to a
  session law the amendment parser reports as amending it.

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
