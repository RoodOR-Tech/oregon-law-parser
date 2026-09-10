# Reviewed chapter 653 previews

These three plans fill existing verified-reference gaps. They do not extend the
13-reference review set or claim complete coverage of other amendments.

| ORS section | Reviewed law | Edited paragraph | Effective and operative date |
| --- | --- | --- | --- |
| 653.020 | 2026 c.2 section 1 (SB 1518) | (14) | January 1, 2027 |
| 653.547 | 2026 c.2 section 2 (SB 1518) | (1)(b)(B)(ix) | January 1, 2027 |
| 653.307 | 2026 c.7 section 1 (HB 4013) | (1) | January 1, 2027 |

The corresponding A/R rows were independently reviewed on PDF page 4 and are
already frozen in `../2026-amendment-table-expansion.json`.

All three pages of [chapter 2](https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2026orlaw0002.pdf)
and the single page of [chapter 7](https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2026orlaw0007.pdf)
were visually reviewed, including the complete amended bodies and final-page
effective dates. Neither act contains an emergency clause, deferred operative
clause or separate applicability clause. Federal-reference dates within the
amended bodies are retained as text; they are not the amendments' operative dates.

Each complete enacted body was independently extracted using PDFium and frozen
in its `*-enacted.txt` file before evaluating the new preview against actual
session-parser output. Curly quotes are preserved; bracketed deletions,
discretionary line-break markers, running headers/footers and whitespace are
normalized. No substantive text corrections were needed.

The canonical 2025 ORS bases were generated from the source-pinned chapter 653
HTML through `decode_markup`, `parse_chapter`, `build_rows` and
`build_section_rows`. Each reviewed paragraph replacement was applied once;
the resulting complete body equals the independently frozen enacted text after
whitespace normalization. Source URLs, byte counts, hashes and retrieval times
are preserved in the bases and plans. Canonical rows remain unchanged.

The catalog now has seven text plans and six unplanned references. CI checks the
day before and on January 1, 2027: three/six applied previews and four/one
scheduled previews respectively. The later ORS 696.370 successor remains pending
until July 1, 2027. Unit tests compare all three complete enacted bodies, dates
and the absence of premature application.
