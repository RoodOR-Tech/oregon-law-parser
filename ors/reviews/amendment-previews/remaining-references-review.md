# Completion of the 13-reference preview set

The final six plans cover the existing reviewed references below. Every full
enacted body was independently extracted from the official source and visually
reviewed before evaluating generated previews. This completes text plans for the
13-reference set, not all references in the statewide amendment table.

| ORS section | Session law | Source pages reviewed | Effective / operative date |
| --- | --- | --- | --- |
| 659A.043 | 2026 c.109 section 55 (HB 4040) | 42–44 | April 7, 2026 |
| 659A.046 | 2026 c.109 section 56 (HB 4040) | 42–44 | April 7, 2026 |
| 659A.049 | 2026 c.109 section 57 (HB 4040) | 42–44 | April 7, 2026 |
| 659A.063 | 2026 c.109 section 58 (HB 4040) | 42–44 | April 7, 2026 |
| 659A.885 | 2026 c.57 section 5 (HB 4111) | 1–4 | June 5, 2026 |
| 658.991 | 2026 c.53 section 4 (HB 4089) | 1–2 | January 1, 2027 |

Chapter 109 section 61 is an emergency clause; page 44 prints April 7, 2026.
A search of the complete act identified operative-date clauses in sections 4,
8, 13, 22, 39 and 42. Their expressly named amendments are unrelated to sections
55–58. The earlier operative-date language inside the bracketed deletion in
section 27 is not a new operative clause for these amendments.

Chapter 57 section 9 uses the 91st day after adjournment; page 4 prints June 5,
2026. Chapter 53 page 2 prints January 1, 2027. Both shorter acts were reviewed
in full and do not defer these amendments further. Source URLs, byte counts,
hashes, retrieval times and page provenance are in each plan.

PDFium extraction preserves curly quotes. Running headers/footers, discretionary
line-break markers and bracketed deleted text are removed; whitespace and spaces
before punctuation left by deletion are normalized. In chapter 57, the page break
splits “review”; the page-one footer and page-two header are removed before
joining the split word. The complete cleaned bodies are frozen in the six
`*-enacted.txt` files. The two printed references to section 4 of the 2026 Act in
659A.885 remain intact; no future ORS codification is invented.

The five chapter 659A bases come from the existing source-pinned canonical gold
acquisition. The chapter 658 base comes from a separate pinned HTML acquisition
through the canonical parser. That source exposed a parser bug: a separate
underscore rule after 658.991's legislative credit caused the credit and rule to
remain in body text. The parser now removes only a terminal standalone underscore
rule following a dated source credit before splitting that credit. Regression
tests preserve statutory form blanks, nonterminal rules and body offsets. The
base was regenerated through the corrected parser, not manually cleaned.

Review also identified an extraction space before the comma following the
bracketed deletion in c.2 section 2. The 653.547 plan, frozen full text and digest
now use the visually printed `companionship services, as defined`; an explicit
regression assertion covers this correction.

CI requires all 13 verified references to have plans and checks every applicable
date transition. The catalog preserves all 12 original section rows and all 13
versions. Before the final July 2027 transition, future plans remain scheduled.
Completeness is limited to this explicitly reviewed reference set; it does not
certify current law or an official consolidated edition.
