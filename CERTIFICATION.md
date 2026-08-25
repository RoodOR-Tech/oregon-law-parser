# Release Certification Baseline

This repository reached its first release-certifying parser baseline on August 25, 2026.

## Frozen benchmark

The certification benchmark is the 50-document independently reviewed gold corpus in `gold/manifest.json` as merged by commit `af283ac5919e84d50e01070db18fa5c5c9b66072` from PR #16.

The exact certifying candidate head was `01f7fb379597c7ba00dacfb4f14d5819b120b6a5`.

Certification metrics from CI #100:

- gold documents: 50
- release certifying: true
- section precision: 1.000
- section recall: 0.9981
- metadata exact match: 1.000

The corpus includes independently reviewed positive controls, negative controls, mixed amendment/repeal acts, degraded-layout sources, legacy HTML, special sessions, delayed effective dates, emergency clauses, prior-session-law amendments, incidental ORS citations, added-to provisions, and large multi-section acts.

## Benchmark governance

The 50-law certification corpus is a baseline, not a tuning set to be casually rewritten.

Changes to gold expectations must be supported by authoritative Oregon legislative sources and an explicit independent re-review. Parser failures should be fixed in parser behavior rather than by weakening gold expectations merely to satisfy CI. Source URLs and hashes must remain pinned and provenance/conflict diagnostics must remain available.

CI must continue to report `gatePassed: true`, `releaseCertifying: true`, and at least the configured release-certification minimum document count.

## Validation beyond the frozen benchmark

Future reliability work should use a separate unseen validation corpus so parser development is not evaluated only against examples already used during hardening. A practical next target is 25 to 50 additional laws selected independently of parser output and kept separate from the frozen certification baseline until reviewed under an explicit promotion process.

## Release posture

The certifying 50-law state is suitable for a release candidate. A versioned GitHub release/tag should point to a commit that preserves this certification gate or improves on it without regression.
