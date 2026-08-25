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

The second pass removed crash-oriented parsing from the production path and made source identity explicit. Successful output includes source path, optional canonical URL, SHA-256 digest, and processing timestamp. Required metadata parsing now returns structured errors rather than terminating through `error` calls.

## Pass 3 — Legislative Counsel ingestion and section evidence

The third pass made both parser evidence and independent LC evidence inspectable. Validation includes section-level title/body evidence, while typed LC CSV ingestion preserves source year, chapter, Oregon Laws section, source URL, volume, and action. `added_to` evidence is retained without being misclassified as amendment/repeal verification.

## Pass 4 — gold-standard corpus and measurable quality gates

The fourth pass introduces a fixed gold corpus under `gold/` plus a deterministic evaluator under `tools/evaluate_gold.py`.

### Gold-label discipline

Gold expectations must be independently reviewed against the underlying Oregon Laws document or another authoritative source. They must never be generated from the parser being evaluated.

The seed corpus begins with Oregon Laws 2022 chapter 2, manually labeled for required metadata and ORS amendment/repeal actions.

### CI quality metrics

CI now parses every manifest document and computes micro-averaged metrics over `(action, ORS section)` pairs:

- section precision target: **>= 99.9%**
- section recall target: **>= 99.5%**
- required metadata exact-match target: **100%**

A `gold-quality-report` artifact records true positives, false positives, false negatives, per-document discrepancies, measured rates, and target thresholds.

### Certification maturity

A passing quality gate only means the parser matches the currently reviewed corpus. The report separately exposes `releaseCertifying`; this remains false until at least 50 independently reviewed laws are present and all thresholds pass. The longer-term target remains 250-500 documents spanning regular and special sessions and known structural edge cases.

## Remaining reliability work

1. Expand the gold corpus to at least 50 independently reviewed laws, then toward 250-500.
2. Populate complete normalized LC datasets from official update tables and use them to accelerate independent corpus review.
3. Add conflict-review reporting that joins parser evidence, LC evidence, and gold expectations.
4. Add page-level evidence coordinates when extraction exposes reliable page boundaries.
5. Replace remaining heuristic text cleanup, especially aggressive hyphen repair, with layout-aware normalization.
