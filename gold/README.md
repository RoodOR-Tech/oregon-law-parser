# Gold-standard corpus

This directory contains fixed, independently reviewed expectations used to measure parser accuracy. Gold labels must never be generated from the parser under test.

## Review rule

Each document added to `manifest.json` must be checked against the underlying Oregon Laws session law and have its expected metadata and ORS amendment/repeal set recorded manually or by an independent authoritative source with human review.

At minimum, review:

- Oregon Laws year and chapter
- bill chamber and number
- effective date
- ORS sections amended
- ORS sections repealed
- unusual operative-section structure that could affect extraction

## Quality metrics

The evaluator treats `(action, ORS section)` as the classification unit and computes micro-averaged precision and recall across the corpus.

Current targets:

- section precision: **>= 99.9%**
- section recall: **>= 99.5%**
- required metadata exact match: **100%**

A CI run fails if the current corpus falls below those thresholds.

## Certification maturity

The initial corpus is deliberately marked `seed-non-certifying`. A green quality gate means the parser matches all reviewed examples currently in the corpus; it does **not** by itself establish production-grade accuracy.

`releaseCertifying` remains false until the manifest contains at least **50 independently reviewed session laws** and all quality thresholds pass. The longer-term target is 250-500 laws spanning regular and special sessions, amendments, repeals, lettered ORS chapters, session-law cross-references, added-to provisions, unusual layouts, and known extraction edge cases.

## Adding a document

1. Add the source PDF under `fixtures/` or another stable corpus location.
2. Verify the law against an authoritative Oregon source.
3. Add one manifest entry with a stable `id`, fixture path, authoritative source URL, review basis, and expected output.
4. Run CI and inspect the retained `gold-quality-report` artifact.
5. If parser output differs, resolve the parser or gold-label error explicitly; never update gold labels merely to make CI pass.
