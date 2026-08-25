# 50-law corpus expansion plan

The first release-certifying milestone is 50 independently reviewed Oregon session laws. Selection is deliberately stratified so the corpus tests parser failure modes rather than merely accumulating easy examples.

## Sampling targets

| Coverage class | Minimum target |
| --- | ---: |
| Straightforward single ORS amendment | 8 |
| Multiple ORS amendments | 8 |
| ORS repeals | 5 |
| Mixed amendment + repeal | 4 |
| No ORS amendment/repeal (negative controls) | 5 |
| Uncodified session-law amendments/repeals | 4 |
| Added-to provisions | 4 |
| Lettered ORS chapters | 3 |
| Prior-session-law cross-references | 3 |
| Special-session laws | 3 |
| Unusual or degraded PDF/layout cases | 3 |
| Known title/body disagreement or extraction edge cases | 3 |

A single document may satisfy more than one coverage class. The final set should span multiple sessions and both House and Senate measures.

## Admission requirements

A document is counted toward the 50-law milestone only when:

1. the source PDF is stored at a stable fixture path;
2. `reviewStatus` is `independently-reviewed`;
3. metadata and ORS amendment/repeal expectations are checked against authoritative Oregon legislative sources;
4. `reviewSources` records the sources used;
5. `reviewBasis` explains any non-obvious legal interpretation, especially negative controls, uncodified-law changes, and added-to provisions;
6. `caseTags` identify the coverage characteristics exercised by the law; and
7. CI passes manifest validation and the gold quality gate.

## Review priority

Selection should favor laws that are likely to expose parser weaknesses:

- title/body disagreement;
- multiple operative `SECTION` clauses;
- repeals and amendments in the same law;
- ORS references embedded in replacement text that are not themselves amended;
- uncodified-law amendments containing incidental ORS citations;
- lettered chapter identifiers such as `475C`;
- emergency clauses and nonstandard effective-date language;
- special sessions and repassed measures;
- page breaks or hyphenation near operative markers;
- measures that amend prior Oregon Laws sections rather than ORS sections.

## Certification rule

Fifty documents is the minimum release-certification threshold, not the end state. The longer-term target remains 250-500 independently reviewed laws. Corpus composition and quality matter more than raw count.
