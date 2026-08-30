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

## Increment 3 — notes and source credits (credits and stubs done)

- `ors_section_note` rows, keeping notes out of `body_text`.
- `ors_source_credit` rows parsed from bracketed legislative history. Done:
  `tools/ors_credits.py` parses every real form recorded in FINDINGS.md --
  plain citation lists, per-citation `Amended by`/`Repealed by`/`Derived
  from` keywords (the final disposition in a stub wins), numbered and bare
  `s.s.` special-session markers, plural-section (`§§2,3`) and
  single-section-with-subsections (`§8(2),(3)`) citations, citations joined
  by "and" instead of a semicolon, subsection-scoped citation prefixes
  (`subsection (3) enacted as ...`), and the non-citation `Formerly X` / bare
  `Renumbered X` forms (including a `Formerly` naming a subsection range),
  which are captured as `formerlyReferences`/`renumberReferences` rather than
  forced into a citation shape. A credit segment matching none of these is
  reported as `unparsedCreditSegmentCount`, gated at zero, rather than
  silently dropped -- the same discipline that caught the dropped title and
  the missing chapter names in increment 2.
- Subsection-level detail is intentionally not modeled: "subsection (3)
  enacted as ..." and the "(2),(3)" suffix in `§8(2),(3)` are read past to
  reach the citation underneath, but which subsection is not itself a column
  anywhere. `SCHEMA.md`'s "Deferred to a later schema version" section lists
  subsection-level decomposition as its own future table; a subsection-scoped
  `ors_source_credit` would join to that table once it exists, rather than
  this increment inventing a column for it now.
- `ors_section_note` rows for editorial and preface notes. In progress,
  measurement stage: `tools/ors_section_notes.py` finds candidate
  `Note:`/`Notes:` introductions in `body_text` the same generous,
  unopinionated way `ors_cross_references.py` measures citation shapes
  before `ors_cross_reference` rows are built, reported as
  `editorialNoteCandidateCount` with per-candidate context, diagnostic only
  and not yet gated. The first real CI run found 152 candidates across the
  sample at zero cost to the gate, and they resolve into three distinct
  shapes rather than free text (see FINDINGS.md for the verbatim forms): a
  "series membership" note naming an ORS chapter or range the section was
  or was not folded into; a "See note under NNN.NNN" cross-reference
  pointing at another section's already-printed note instead of repeating
  it; and a quoted uncodified session-law provision naming
  `(session_year, session_law_chapter)` -- the same deferred table
  SCHEMA.md's "temporary and uncodified provisions" item already
  anticipated, now backed by real data instead of a hypothetical. A rarer
  fourth shape, a bare cross-reference with no session citation
  (`Note: See 105.844.`), was also seen once and is not yet placed. The
  extraction rule itself is not yet written.
- Repealed and renumbered sections. Done, after three wrong guesses and one
  ground-truth dump. Cross-reference candidate measurement first proved the
  gap was real (numbers like `1.165`/`1.167` embedded *inside* a different
  section's own `body_text`); two attempts at fixing `normalize_chapter_
  text`'s newline handling each measured **zero change** against the real
  sample chapters, both wrong about the mechanism (there was no missing
  newline to preserve). `find_embedded_stub_markup_samples` dumped the
  actual raw markup instead of guessing again, and it showed the real form:
  every stub-only section prints in its own `<p>`, with the number **bold**
  and its bracket in a **separate, non-bold `<span>`** right after it --
  `<b><span>      1.055</span></b><span> [1959 c.638 §1; repealed by 2015
  c.212 §2]</span>`. `SECTION_CATCHLINE_PATTERN` and `SECTION_STUB_PATTERN`
  both require the catchline or bracket inside the bold run's own text; a
  bold run that is only the bare number matches neither, so it was silently
  dropped as a non-anchor. The anchor-building loop now recognizes this
  third case: a bold run that is exactly a bare number, with a bracket
  immediately following it outside the bold span, anchors a stub the same
  way a keyword-led or citation-led bracket already does. Verified against
  the real markup for `1.055` and a run of three consecutive real stubs,
  each becoming its own correctly-classified section with the preceding
  operative section's own text and credit unaffected -- the credit-
  collision concern raised earlier turned out to resolve itself once the
  stub is a real anchor, since the preceding section's span then correctly
  ends where the stub begins. Confirmed against real CI data, the first
  genuinely confirmed change in four attempts: `sectionRowCount` rose from
  892 to 1122 and `statusCounts` went from 100% `operative` to real
  `repealed`/`renumbered` counts, zero problems, zero integrity violations.
  Splitting out 230 sections that had never stood on their own before
  immediately surfaced two follow-ons, both fixed: the anchor lookahead for
  a stub's bracket had a 400-character cap that a long citation list (real
  chapter 192 example) could exceed, silently missing the close -- removed,
  matching the uncapped search an ordinary operative section's own trailing
  credit already gets; and a new non-citation credit form, a compound
  subsection-scoped renumber note naming two destinations joined by "and"
  (`subsections (1) to (3) renumbered 192.411 and subsections (4) to (7)
  renumbered 192.401 in 2017`), added to `ors_credits.py` alongside the
  existing bare-renumber and Formerly forms.
- This is the table that joins to the amendment parser's `(year, chapter)`
  output. The join is data-only; neither program imports the other.

## Increment 4 — cross references and the relational build

- `ors_cross_reference` rows, with unresolved citations preserved rather than
  dropped. In progress, measurement stage: `tools/ors_cross_references.py`
  finds candidate section, range and chapter mentions in `body_text` and
  reports them (count, a by-kind breakdown, and per-candidate context) as
  `crossReferenceCandidate*` fields, diagnostic only and not yet gated --
  the same order every earlier table in this pipeline followed (probe
  before parse, unparsed-segment count before the credit rule, stub-line
  count before an anchoring rule). The patterns tried are deliberately
  generous (any `NNN.NNN`, `NNN.NNN to NNN.NNN`, or `chapter NNN` shape) so
  real phrasing is seen from CI before `reference_kind` values and
  `to_section_id` resolution are designed against it.
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
