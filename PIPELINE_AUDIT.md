# Portable pipeline audit

The default branch at `90e40902e9ef99a91339c727cddeb882020078bb` already
contained a mature ORS pipeline in `ors/tools`, a richer provenance-oriented
`ors_*` schema, 400 ORS tests (three skipped without staged sources), and a
separate Haskell session-law parser in `analyze/src`.

`Amendment.hs` distinguishes title assertions from operative clauses. This
matters: an act amending an earlier session-law provision may mention ORS
without directly amending the mentioned statute. `Tika.hs` and the legacy CI
require Java/Tika and Stack. The new CLI does not invoke those tools.

The ORS parser anchors body sections on bold runs, distinguishes the repeated
table of contents, decodes Word HTML using its declared charset, and retains
source credits and notes. `diff_ors_editions.py` compares canonical section
rows; it is not a substitute for extracting legislative edit typography.

Draft PR #89 provided the initial installable Python adapter, five compact
tables, cache, manifest interface, Parquet export and Windows/Linux CI.
Its five remote workflow checks passed on commit `54f54e8`; that result does
not validate subsequent changes. The prior statewide run failed because an
in-body reference to the 1991 Edition was interpreted as a publication banner.
Local follow-up work had started addressing this and four-digit UCC numbers.

The continuation uses the same branch and source cache. It adds regression
coverage for publication-only identity, former-provision footers, bounded
pending notes, literal form brackets, mixed PDF layouts, alternate printed
versions, header-derived special-session ordinals, partial-word font changes,
operative repeal headings, pinned replay and preservation of published output.

Historical acquisition is checked against the archive's advertised edition
document count where available. A discovered roster is not a legal
certification: unsupported operative clauses remain visible in `diagnostics`.
The Haskell gold certification and frozen ORS review corpora remain independent.
