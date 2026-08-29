# ORS Relational Table — parallel effort

This directory is a **separate, parallel effort** from the session-law amendment
parser that occupies `analyze/`, `tools/`, `gold/`, `operations/` and
`validation/`.

| | Amendment effort (existing) | ORS effort (this directory) |
|---|---|---|
| Input | One Oregon Laws session-law chapter (PDF/HTML) | The published Oregon Revised Statutes chapters |
| Question answered | "What did this act change?" | "What does the statute book currently say, as rows?" |
| Output | Per-document JSON metadata | Normalized relational tables (JSON/CSV/SQLite) |
| Cadence | Per enacted chapter | Per ORS edition — once or twice a year |
| Code | Haskell (`analyze/`) + Python tooling (`tools/`) | Python only (`ors/tools/`) |

**Non-interference rule.** Work in this directory must not modify
`analyze/`, `tools/`, `gold/`, `operations/`, `validation/`, `fixtures/`, or any
existing workflow. The frozen 50-law certification corpus and the 25-law unseen
validation corpus belong to the amendment effort and are out of scope here. The
one deliberate connection is one-directional and data-only: the
`ors_source_credit` table emits `(session_year, session_law_chapter,
session_law_section)` tuples that join to the amendment parser's output. Neither
program imports the other.

## Goal

Produce a relational data table covering all of the Oregon Revised Statutes as
published at <https://www.oregonlegislature.gov/bills_laws/pages/ors.aspx>,
rebuildable on demand whenever a new edition is published (typically once or
twice a year, after each regular and special session).

The schema is defined in [SCHEMA.md](SCHEMA.md).

## Principles inherited from the amendment effort

These are deliberate carry-overs, because they are what made the existing parser
certifiable:

1. **Pinned provenance.** Every acquired byte stream records its exact source
   URL, SHA-256 digest, byte count and retrieval timestamp. Nothing is
   synthesized silently.
2. **Structured failures.** Tools report failures as data in a
   `schemaVersion`-stamped JSON report and exit non-zero. They do not crash and
   do not silently drop rows.
3. **Independently reviewed expectations.** Correctness is measured against gold
   rows established from the authoritative source, never generated from the
   parser being evaluated.
4. **No tuning to the benchmark.** A parser defect is fixed in the parser, not
   by rewriting a reviewed expectation.
5. **Deterministic, dependency-free tooling.** Python 3 standard library only,
   so CI needs no package installation step.

## Build stages

The pipeline is deliberately staged so each stage is separately inspectable and
separately gated.

| Stage | Tool | Status |
|---|---|---|
| 1. Read the published volumes, titles and chapter ranges | `tools/acquire_ors_roster.py` | implemented |
| 1b. Build a chapter roster by verified enumeration | — | not started |
| 2. Acquire chapter sources with pinned provenance | `tools/acquire_ors_chapters.py` | implemented |
| 3. Fingerprint chapter markup to establish ground truth | `tools/probe_ors_structure.py` | implemented |
| 4. Parse chapters into `ors_section` rows | `tools/parse_ors_chapter.py` | implemented |
| 5. Extract `ors_source_credit` and `ors_cross_reference` rows | — | not started |
| 6. Emit CSV / SQLite relational build | — | not started |
| 7. Gold row corpus and quality gate | — | not started |

Stages 1-3 are implemented first on purpose. The published ORS markup is the one
thing that cannot be guessed from outside: stage 3 exists so the real structure
is measured from the authoritative source and recorded, before any parsing rule
is written against it.

## Running the implemented stages

Read the table of titles — volumes, titles and the chapter range each covers:

```bash
python3 ors/tools/acquire_ors_roster.py \
  --output ors-sources/ORS_TitlesChapters.pdf \
  --tika-jar tika-app-2.8.0.jar \
  --report ors-roster.json
```

Acquire the fixed development sample, checked against the published ranges —
what routine CI runs do:

```bash
python3 ors/tools/acquire_ors_chapters.py \
  --title-roster-file ors-roster.json \
  --chapters-file ors/sample/chapters.json \
  --output-dir ors-sources \
  --report ors-acquisition.json
```

A chapter falling under no published title is rejected before anything is
fetched. Omitting `--title-roster-file` skips that check; the report then
records `titleRangesChecked: false` so it can never be mistaken for a checked
run.

Fingerprint what was acquired:

```bash
python3 ors/tools/probe_ors_structure.py \
  --acquisition-report ors-acquisition.json \
  --report ors-structure-probe.json
```

Parse the acquired chapters into relational rows:

```bash
python3 ors/tools/parse_ors_chapter.py \
  --acquisition-report ors-acquisition.json \
  --report ors-parse.json \
  --rows ors-rows.json
```

`ors-rows.json` holds `ors_edition`, `ors_chapter`, `ors_subdivision` and
`ors_section` rows. The run fails if any `SCHEMA.md` invariant is violated, or
if a chapter states no edition year — `edition_id` is the primary key of
`ors_edition`, so a row that cannot be filed against an edition is not emitted
at all.

## The fixed development sample

Routine CI acquires only the chapters named in
[`sample/chapters.json`](sample/chapters.json). The roster is chosen to span the
structural cases the parser has to survive — the first chapter, a long
subdivided chapter, one dense with repeal stubs, a small one, one with long
multi-session credits, and two lettered chapters at opposite ends of the
numbering — rather than to be representative by volume. Each entry records why
it is there.

Keeping the sample small is a cost decision as much as a speed one: a cycle is a
handful of requests instead of several hundred, so iteration on parsing rules
stays cheap. Whole-edition runs happen on demand through the workflow's
`whole-edition` dispatch scope.

The sample is a development aid, not a corpus. It establishes no correctness
expectations. Gold rows come later, in increment 5, under independent review.

## Tests

Every test is offline, using synthetic fixtures and a loopback HTTP server, so
the suite runs on a machine with no network egress. The roster tests drive the
real Tika extraction path against a synthetic roster PDF, and skip themselves
if Java or the Tika jar is unavailable:

```bash
python3 -m unittest discover -s ors/tests -v
```
