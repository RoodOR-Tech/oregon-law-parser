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
  response, which is verification rather than guessing. Built:
  `tools/enumerate_ors_chapters.py`. For each integer inside a title's own
  declared range (never beyond it, so the published gap between two titles,
  like chapter 11 between titles 1 and 2, is never even probed), the bare
  chapter is always probed, then lettered siblings (`90A`, `90B`, ...) are
  probed starting from `A` regardless of whether the bare number itself
  existed -- verification means not assuming a letter can only exist
  alongside its bare number. The walk for that digit stops at the first
  probe that is not a confirmed chapter; a genuine 404 and an inconclusive
  failure (timeout, 5xx) both end it, but only the 404 is a verified
  absence -- a failure is counted and reported separately (`failureCount`,
  gated at zero) rather than folded into either outcome, so an incomplete
  roster is visible rather than silently reported as complete.
- Lettered chapters are expressed by the ranges themselves (`chs 284-285C`,
  `chs 286A-289`), so enumeration can follow the printed span rather than
  guessing suffixes: `candidate_digit_range` walks only the integer part of
  each title's own `firstChapter`/`lastChapter` (284 to 285 for `chs
  284-285C`), and the letter-probing loop above discovers how far each
  integer's own family actually runs.
- This is a whole-edition operation of several hundred to low-thousands of
  requests (every gap between two published titles costs one extra
  bare-number probe, and every real gap inside a title's range costs one
  bare probe plus one letter-A probe before it is confirmed absent), so it
  runs on manual dispatch, not on every CI run: a new `enumerate-whole-
  edition` job in `ors-table.yml`, gated on `workflow_dispatch` with an
  explicit `enumerate_whole_edition: true` input (plus an optional
  `enumerate_titles` input to scope a run to specific titles), never on
  `push` or `pull_request`.
- The report this tool writes uses the exact per-chapter shape
  `acquire_ors_chapters.py`'s own acquisition report already uses
  (`chapterNumber`, `ok`, `sourceFormat`, `fixture`, `sha256`, `bytes`,
  `titleNumber`, ...), so it can be handed directly to
  `probe_ors_structure.py`, `parse_ors_chapter.py` and
  `build_ors_relational.py` as their acquisition-report input without a
  translation step: a confirmed absence or failure simply carries `ok:
  false` and is filtered out by their existing `chapter.get("ok")` checks,
  the same as a chapter that was requested explicitly but never fetched.
- Not yet confirmed against real data: a whole-edition run against the real
  site is a materially larger one-time action (on the order of a thousand
  requests to a state government site) than anything this pipeline has run
  autonomously so far, so it is held for explicit confirmation before first
  being dispatched, the same way the cross-reference resolution design was
  held for a go-ahead before increment 4 started.

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

## Increment 3 — notes and source credits (done)

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
  the missing chapter names in increment 2. Also fixed: a section whose
  credit is immediately followed by a "Note:" block (found while
  cataloging the real note forms below) was not reaching
  `unparsedCreditSegmentCount` at all -- it never became an
  `ors_source_credit` row in the first place, because the credit-splitting
  rule required the bracket to reach the true end of the string. See
  FINDINGS.md for the real fragment and the fix.
- Subsection-level detail is intentionally not modeled: "subsection (3)
  enacted as ..." and the "(2),(3)" suffix in `§8(2),(3)` are read past to
  reach the citation underneath, but which subsection is not itself a column
  anywhere. `SCHEMA.md`'s "Deferred to a later schema version" section lists
  subsection-level decomposition as its own future table; a subsection-scoped
  `ors_source_credit` would join to that table once it exists, rather than
  this increment inventing a column for it now.
- `ors_section_note` rows for editorial and preface notes. Done for
  extraction; sub-classifying the three real shapes is not. Measurement
  first (`tools/ors_section_notes.py`'s `find_editorial_note_candidates`,
  the same generous, unopinionated way `ors_cross_references.py` measures
  citation shapes before `ors_cross_reference` rows are built): the first
  real CI run found 152 `Note:`/`Notes:` candidates across the sample at
  zero cost to the gate, resolving into three distinct shapes rather than
  free text (see FINDINGS.md for the verbatim forms) -- a "series
  membership" note naming an ORS chapter or range the section was or was
  not folded into; a "See note under NNN.NNN" cross-reference pointing at
  another section's already-printed note instead of repeating it; and a
  quoted uncodified session-law provision naming
  `(session_year, session_law_chapter)` -- the same deferred table
  SCHEMA.md's "temporary and uncodified provisions" item already
  anticipated, now backed by real data instead of a hypothetical. A rarer
  fourth shape, a bare cross-reference with no session citation
  (`Note: See 105.844.`), was also seen once and is not yet placed.
  That measurement also settled the one question extraction needed: every
  real note runs from its own introducer to the next one, or to the end of
  the section's text if it is the last. `split_editorial_notes` uses that
  rule, run before the existing credit/body split (a section's own credit
  always comes before its first note, stub or operative alike), so
  `ors_section_note` rows are now emitted with proper offsets and
  `body_text` no longer carries note text. `note_kind` stays
  `editorial_note` for all three shapes -- SCHEMA.md's enum has no other
  value for this case yet, and splitting the shapes apart is deferred
  until something needs to join against them differently.
  `editorialNoteCandidateCount` is kept on rather than removed: it now
  measures survivors after extraction instead of the gap before it.
  Confirmed against real CI data at exactly zero (`sectionNoteRowCount`
  152, matching the earlier measurement precisely), it is now gated --
  the same measure-then-gate order every earlier field in this pipeline
  followed.
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

## Increment 4 — cross references and the relational build (done)

- `ors_cross_reference` rows, with unresolved citations preserved rather than
  dropped. Measurement first, as every earlier table in this pipeline did
  (probe before parse, unparsed-segment count before the credit rule,
  stub-line count before an anchoring rule): `tools/ors_cross_references.py`
  finds candidate section, range and chapter mentions in `body_text`,
  deliberately generous (any `NNN.NNN`, `NNN.NNN to NNN.NNN`, or `ORS
  chapter NNN` shape), and reports them as `crossReferenceCandidate*`
  fields. Two real wrinkles the first CI run surfaced are both fixed: a
  bare "chapter NNN" mention is not always an ORS chapter (a session-law
  chapter, "chapter 88, Oregon Laws 2025", printed the same shape), fixed
  by requiring an "ORS" lookbehind rather than catching and rejecting it
  after the fact; a bare section mention sometimes carries a subsection
  suffix like `(3)`, needing no code change since the existing pattern
  already stops at the section number. See FINDINGS.md for the real forms.
  `resolve_cross_references` now turns those candidates into rows:
  `reference_kind` is `section`, `range_start`, `range_end` (a range
  becomes two rows, one per endpoint, per SCHEMA.md) or `chapter`;
  `to_section_id` resolves against every section this build has parsed
  (across all its chapters, not just the citing section's own), staying
  null for a citation the fixed seven-chapter sample cannot resolve or a
  `chapter` reference (which names no single section for the schema's own
  foreign key to point at) -- unresolved per citation, not per candidate
  kind, matching SCHEMA.md's own note that an unresolved citation is real
  data. Offsets are absolute into the chapter's own normalized text, the
  same as every other row, derived from `body_text`'s own start offset
  rather than re-scanned after the fact (see `bodyTextCharOffsetStart`'s
  comment in `parse_ors_chapter.py`). Confirmed against real CI data:
  `crossReferenceRowCount` 4110 (exactly the 3476 measured candidates plus
  634 range candidates each becoming two rows), `crossReferenceResolvedCount`
  2363 (57.5%, higher than expected since several sample chapters are large
  enough to frequently cite themselves). See FINDINGS.md for the detail.
- CSV emission per table and a SQLite build from the CSVs. Done:
  `tools/build_ors_relational.py` joins `parse_ors_chapter.py`'s own rows
  with the roster and acquisition reports (neither of which the parser
  itself ever sees) into all nine of SCHEMA.md's tables -- `ors_edition`
  through `ors_acquisition_event` -- with SCHEMA.md's own snake_case
  columns, and emits each as NDJSON, CSV and a SQLite database built by
  reading the CSVs back (SCHEMA.md's own words: the CSVs, not the in-memory
  rows, are the database's source, so a database can be rebuilt from a set
  of CSV files alone). Two joins neither source report carries on its own:
  `ors_chapter.source_format`/`.retrieved_at` come from the acquisition
  ledger's own per-chapter record, matched by chapter number; `ors_
  acquisition_event.edition_id` isn't knowable from the ledger alone since
  edition identity is only established from a chapter's own content after
  the fact, so every event in a build -- the roster fetch included --
  is filed under the one edition that build parsed, the same
  single-edition-per-build assumption `resolve_cross_references`'s own
  `section_ids_by_number` map already relies on. No new measurement was
  needed to write this: SCHEMA.md had already committed to every column
  and join before this increment started, only the row-shaping was new.
  Referential integrity is not re-checked in this tool: `parse_ors_
  chapter.py`'s own gate already covers everything it emits, and this tool
  only reshapes and joins, it does not invent new facts to validate.
- The referential integrity checks listed in `SCHEMA.md` become a CI gate.
  Substantially already true: `parse_ors_chapter.py`'s own Python-level
  `check_referential_integrity` runs on every build and the workflow's own
  gate step requires `integrityViolationCount == 0`, so a violation already
  fails CI today. What is not yet a distinct, explicit gate step is a
  single command a reviewer can point at as "the SCHEMA.md gate" the way
  the amendment effort's gold gate is one command -- worth a follow-up if
  that distinction ever matters, but not a real coverage gap today.

## Increment 5 — gold rows and a quality gate

- A small independently reviewed corpus of chapters with expected section rows,
  established from the authoritative source and never from parser output.
- Precision and recall over `(chapter, section_number)` pairs, plus exact-match
  rates for catchline and status.
- Thresholds set only after a first measurement, so they describe the parser
  rather than flatter it.

Source staging done: the candidate selection (`ors/gold/pending/selection.json`)
freezes five chapters outside the development sample -- `12`, `105`, `183`,
`471` and `659A` -- chosen to span an ordinary numeric chapter, a very large
civil-property chapter, dense administrative-procedure cross-references, a
large regulatory chapter, and a lettered chapter carrying published 2026
pending-change notices, before any parser evaluation of them.
`tools/stage_ors_gold_sources.py` then proves the selection and the acquired
bytes match exactly (same chapter set, same source URLs, real SHA-256
digests) and asserts no parser artifact (`ors-rows.json`, `ors-parse.json`,
`ors-build.json`) exists alongside the staging run, so the source registry
can never be quietly built from something the parser already touched.
`ors-gold-source-staging.yml` runs this on its own PR trigger and on manual
dispatch; confirmed against a real dispatch run (workflow run `33570106878`):
all 5 sources acquired, digests pinned in
`ors/gold/reviews/source-staging-provenance.json`.

Independent review done for 3 of the 5 chapters so far:

- Chapter 12 (pilot, 52 sections): `ors/gold/reviews/chapter-12-expected-sections.json`.
  Exact match against the parser's real output (52/52 sections, every status,
  every catchline) once one review-side defect -- a missing trailing period,
  confirmed against the raw bold markup -- was fixed in the review itself.
- Chapter 105 (251 sections, the largest of the five): `ors/gold/reviews/chapter-105-expected-sections.json`.
  Catchlines were extracted with a small auditable script over the frozen
  source's own `<b>` runs (independent of `parse_ors_chapter.py`), all 217
  operative sections cross-checked 1:1 against the chapter's own table of
  contents, and the other 34 sections found by a second script pass matching
  bare numbers immediately followed by a bracketed legislative-history
  citation. This review caught a real parser bug: `SECTION_CATCHLINE_PATTERN`
  required a catchline to open with a capital letter, so the two sections
  whose catchlines quote the term they define -- 105.850 and 105.900, both
  printed as `“Term” defined for ORS ...` -- matched neither the catchline
  pattern nor the stub pattern and were silently dropped as unrecognized bold
  runs. Fixed by widening the pattern's lookahead to also accept a leading
  quotation mark, with a regression test
  (`QuotedTermCatchlineTest`) reproducing the exact 105.850 markup. Re-run
  against the fix: exact match, 251/251 sections, every status, every
  catchline, every `renumbered_to`.
- Chapter 183 (109 sections): `ors/gold/reviews/chapter-183-expected-sections.json`.
  Same auditable-script method as chapter 105: 83 operative catchlines
  extracted from the frozen source's own `<b>` runs, cross-checked 1:1
  against the table of contents, and 26 more sections (22 repealed, 4
  renumbered) found by the bracketed-citation script pass. Eight of those 26
  (`183.010` through `183.090`) are historical numbers from the chapter's
  pre-1971 numbering scheme, printed as a block before the first live section
  rather than scattered through the chapter -- the same disused-number
  convention as chapters 12 and 105, just concentrated at the head instead of
  spread out. Checked against the parser's real output: exact match, 109/109
  sections, every status, every catchline, every `renumbered_to` -- a clean
  confirmation this time, no parser defect found.

Not yet done: the remaining 2 chapters (`471`, `659A`), and the
precision/recall tool and CI gate built against all five reviews.

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
