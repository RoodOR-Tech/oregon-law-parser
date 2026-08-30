# Release Certification Baseline

This repository reached its first release-certifying parser baseline on August 25, 2026. Reliability evidence is maintained in three separate layers: the frozen 50-law certification corpus, the separately frozen 25-law unseen-validation corpus, and full-session operational validation.

## Frozen 50-law benchmark

The certification benchmark is the 50-document independently reviewed gold corpus in `gold/manifest.json` as merged by commit `af283ac5919e84d50e01070db18fa5c5c9b66072` from PR #16.

The exact first certifying candidate head was `01f7fb379597c7ba00dacfb4f14d5819b120b6a5`.

Certification metrics from CI #100:

- gold documents: 50
- release certifying: true
- section precision: 1.000
- section recall: 0.9981
- metadata exact match: 1.000

The corpus includes independently reviewed positive controls, negative controls, mixed amendment/repeal acts, degraded-layout sources, legacy HTML, special sessions, delayed effective dates, emergency clauses, prior-session-law amendments, incidental ORS citations, added-to provisions, and large multi-section acts.

## Frozen 25-law unseen validation

The second benchmark is deliberately separate from the gold corpus. Its 25 laws, authoritative-source hashes, and independently reviewed expectations were frozen before the parser was evaluated against them.

The permanent first-evaluation record is `validation/results/unseen-25-first-evaluation.json`. That first run evaluated 25 documents with 406 true-positive section operations, zero false positives, zero false negatives, section precision 1.000, section recall 1.000, metadata exact match 1.000, and `gatePassed: true`.

The unseen corpus remains a validation set. It is not to be rewritten merely because a later parser change fails against it.

## Full-session operational validation

Operational-scale validation covers the session plans and hard-gate workflows enumerated in `operations/certification-matrix.json`. The matrix is machine-checked against the repository so a session plan or full-session workflow cannot be silently added, removed, or left outside the certification inventory.

The current validated operational floor is **1999**. The established 1997 attempt is a qualified source-availability exclusion, not a parser pass. Its permanent evidence, failed acquisition counts, artifact IDs and SHA-256 digests are recorded in `operations/pre-1999-source-boundary.json`.

A pre-1999 session must not be represented as operationally validated unless authoritative chapter identity and source bytes become reproducibly obtainable with provenance. The 1997 exclusion can be revisited if an authoritative archival chapter-to-bill index, chapter scan set, or equivalent source becomes available.

## Benchmark governance

The 50-law certification corpus and 25-law unseen-validation corpus are baselines, not tuning sets to be casually rewritten.

Changes to reviewed expectations must be supported by authoritative Oregon legislative sources and explicit independent re-review. Parser failures should be fixed in parser behavior rather than by weakening expectations merely to satisfy CI. Source URLs and hashes must remain pinned and provenance/conflict diagnostics must remain available.

CI must continue to report `gatePassed: true`, `releaseCertifying: true`, and at least the configured release-certification minimum document count. Changes affecting operational certification metadata must also pass `tools/validate_operational_certification.py` and the preserved operational hard gates configured for those changes.

## Release posture

A versioned release/tag should point to a commit that preserves all three evidence layers: the frozen gold certification gate, frozen unseen-validation gate, and the applicable full-session operational gates. Qualified source-availability exclusions must remain explicit rather than being converted into passes or omitted from the coverage boundary.
