# Oregon Law Parser — Reliability Hardening

## Pass 1 — operative-section validation

The first hardening pass added an independent parser for operative `SECTION` clauses, reconciled it with title/summary evidence, expanded lettered ORS chapter support, added explicit validation states, and introduced GitHub Actions plus fixture smoke tests.

Validation states are:
- `Verified`
- `ParsedUnverified`
- `Conflict`
- `Incomplete`

The first pass also added Oregon Legislative Counsel reconciliation scaffolding scoped by Oregon Laws year and chapter.

## Pass 2 — provenance and structured failures

This pass removes crash-oriented parsing from the production path and makes source identity explicit.

### Provenance

Successful parser output now includes a `provenance` object with:
- `sourcePath`: input PDF path
- `sourceUrl`: optional canonical URL supplied with `--source-url`
- `sourceSha256`: SHA-256 digest of the exact input PDF bytes
- `processedAt`: UTC processing timestamp

The SHA-256 digest allows downstream datasets to prove exactly which source bytes produced a record and detect silent source replacement.

### Structured parse failures

Required metadata extractors now return `Maybe` values instead of throwing `error`. The production parser aggregates missing or invalid fields into typed `ParseError` values. Current error codes are:
- `MissingCitation`
- `InvalidCitation`
- `MissingYear`
- `MissingChapter`
- `MissingEffectiveDate`
- `ExtractionFailed`

When parsing fails, the CLI emits JSON containing `errors` plus `provenance` and exits non-zero. Missing summaries are represented as JSON `null` rather than the prior sentinel string.

### CI enforcement

The test suite covers malformed/missing metadata without exceptions and confirms provenance survives successful parsing. Fixture smoke tests require a 64-character lowercase SHA-256 digest and non-empty source path.

## Remaining reliability work

1. Ingest the full Oregon Legislative Counsel update tables rather than representative sample rows.
2. Add a gold-standard corpus spanning sessions, special sessions, page layouts, repeals, amendments, added-to ranges, uncodified provisions, and known extraction edge cases.
3. Record section-level evidence and page/`SECTION` provenance rather than only document-level provenance.
4. Add precision/recall release gates and conflict-review reports.
5. Replace remaining heuristic text cleanup, especially aggressive hyphen repair, with layout-aware normalization.
