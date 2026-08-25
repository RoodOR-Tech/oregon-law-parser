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

The second pass removed crash-oriented parsing from the production path and made source identity explicit.

### Provenance

Successful parser output includes a `provenance` object with:
- `sourcePath`: input PDF path
- `sourceUrl`: optional canonical URL supplied with `--source-url`
- `sourceSha256`: SHA-256 digest of the exact input PDF bytes
- `processedAt`: UTC processing timestamp

### Structured parse failures

Required metadata extractors return `Maybe` values instead of throwing `error`. The production parser aggregates missing or invalid fields into typed `ParseError` values. When parsing fails, the CLI emits JSON containing `errors` plus `provenance` and exits non-zero. Missing summaries are represented as JSON `null`.

## Pass 3 — Legislative Counsel ingestion and section evidence

This pass makes both parser evidence and independent LC evidence inspectable.

### Section-level parser evidence

The validation payload now includes `sectionEvidence` records. Each record preserves:
- the affected ORS section number;
- amendment or repeal action;
- whether the evidence came from the title or operative body;
- the Oregon Laws `SECTION` number when the operative body supplied the evidence; and
- the normalized text that triggered the extraction.

This allows a `Conflict` to be reviewed against the exact parser evidence rather than only comparing final section sets.

### Legislative Counsel CSV ingestion

`LegislativeCounsel` now provides `loadLCRecords` and `decodeLCRecords` for the normalized LC CSV contract under `data/legislative-counsel/`. Ingestion uses typed CSV decoding and fails closed on malformed rows or unsupported action values.

Each LC record preserves:
- ORS section/range;
- action (`amended`, `repealed`, or `added_to`);
- Oregon Laws year, chapter, and section;
- LC source URL; and
- ORS source volume.

Reconciliation remains scoped by both year and chapter. `added_to` rows are retained as evidence but are not counted as amendment/repeal evidence and therefore cannot independently produce `LCVerified` or `LCConflict`.

### Validation posture

The parser now has three independent audit layers:
1. title/summary extraction;
2. operative-body extraction with section-level evidence; and
3. Legislative Counsel amendment/repeal reconciliation with retained LC records.

## Remaining reliability work

1. Populate complete normalized LC datasets from the official update tables instead of the representative sample file.
2. Build a gold-standard corpus spanning sessions, special sessions, page layouts, repeals, amendments, added-to ranges, uncodified provisions, and known extraction edge cases.
3. Add page-level evidence coordinates when the extraction layer exposes reliable page boundaries.
4. Add precision/recall release gates and conflict-review reports.
5. Replace remaining heuristic text cleanup, especially aggressive hyphen repair, with layout-aware normalization.
