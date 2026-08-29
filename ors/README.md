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
| 1. Discover the chapter index for an edition | `tools/acquire_ors_chapters.py --index-only` | implemented |
| 2. Acquire chapter sources with pinned provenance | `tools/acquire_ors_chapters.py` | implemented |
| 3. Fingerprint chapter markup to establish ground truth | `tools/probe_ors_structure.py` | implemented |
| 4. Parse chapters into `ors_section` rows | `tools/parse_ors_chapter.py` | not started |
| 5. Extract `ors_source_credit` and `ors_cross_reference` rows | — | not started |
| 6. Emit CSV / SQLite relational build | — | not started |
| 7. Gold row corpus and quality gate | — | not started |

Stages 1-3 are implemented first on purpose. The published ORS markup is the one
thing that cannot be guessed from outside: stage 3 exists so the real structure
is measured from the authoritative source and recorded, before any parsing rule
is written against it.

## Running the implemented stages

Discovery only — lists the chapters an edition publishes, downloads nothing:

```bash
python3 ors/tools/acquire_ors_chapters.py \
  --index-only \
  --report ors-chapter-index.json
```

Acquire the fixed development sample — what routine CI runs do:

```bash
python3 ors/tools/acquire_ors_chapters.py \
  --chapters-file ors/sample/chapters.json \
  --output-dir ors-sources \
  --report ors-acquisition.json
```

Acquire every chapter in the edition — several hundred requests, so this is
opt-in via manual workflow dispatch rather than something CI does on its own:

```bash
python3 ors/tools/acquire_ors_chapters.py \
  --output-dir ors-sources \
  --report ors-acquisition.json
```

Isolate a failure by skipping the index and constructing URLs from explicitly
named chapters:

```bash
python3 ors/tools/acquire_ors_chapters.py \
  --without-index \
  --chapters-file ors/sample/chapters.json \
  --output-dir ors-sources \
  --report ors-acquisition.json
```

Naming a chapter is not the same as synthesizing a roster — the roster is what
must never be guessed. Such a run is marked `rosterVerified: false` and
`chapterUrlSource: "constructed"`, and exists to tell a discovery failure apart
from a chapter-URL failure. It must not be treated as a complete edition.

Fingerprint what was acquired:

```bash
python3 ors/tools/probe_ors_structure.py \
  --acquisition-report ors-acquisition.json \
  --report ors-structure-probe.json
```

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

Every test is offline and uses synthetic fixtures, so the suite runs on a
machine with no network egress:

```bash
python3 -m unittest discover -s ors/tests -v
```
