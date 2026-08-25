# Oregon Law Parser — Hardening Pass 1

This patch is intentionally conservative. It adds an independent parser for operative `SECTION` clauses and reconciles that output with the existing title/summary parser.

## What changes

1. `affectedSections` now prefers operative-body evidence when available.
2. Existing title/summary parsing is retained as a fallback.
3. Output adds a `validation` object containing:
   - `validationStatus`: `Verified`, `ParsedUnverified`, or `Conflict`
   - `titleBodyMatch`
   - `titleSections`
   - `bodySections`
4. The ORS regex now permits any uppercase letter suffix (for example `475C.770`) instead of only A-C.
5. Tests cover operative amendment/repeal clauses, false-positive prevention, lettered chapters, and reconciliation behavior.

## Important limitation

This patch has not been compiled in the ChatGPT runtime because GHC/Stack/Cabal are not installed there. It should therefore be treated as a reviewable implementation patch, not a verified release.

## Recommended merge sequence

1. Run the existing Hspec suite.
2. Run against the two existing PDF fixtures and compare JSON output.
3. Add 25–50 real Oregon Laws fixtures before making operative-body output authoritative for all documents.
4. Next hardening pass: Oregon LC A&R reconciliation, source hashes/provenance, structured parse errors, and a gold corpus with precision/recall gates.
