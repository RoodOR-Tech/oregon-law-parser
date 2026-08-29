# Measured structure of the published ORS chapter documents

Recorded from CI run
[33262966569](https://github.com/RoodOR-Tech/oregon-law-parser/actions/runs/33262966569),
which acquired and probed the fixed development sample. Everything here is
measured from the authoritative source, not assumed. Increment 2's parsing
rules are written against these findings.

## Chapter documents

The chapter URL pattern is confirmed:
`https://www.oregonlegislature.gov/bills_laws/ors/ors{NNN}{letter}.html`.
Chapters 174, 192, 279A and 646A all resolved, including both lettered
chapters, so the letter suffix needs no special-casing in the URL.

Documents are large: chapter 192 is 810 KB, chapter 646A is 1.3 MB.

## They are Word HTML exports, not semantic markup

The tag histogram is almost entirely `span`, `p` and `b`, with one `div` and a
handful of `a`. Chapter 279A carries the single class `WordSection1`; the
others carry no classes at all.

There is therefore no semantic markup to parse. Structure has to be recovered
from typography and text, which is what the rest of these findings describe.

## They are Windows-1252, not UTF-8

The first probe decoded as UTF-8 and produced mojibake throughout:

```
"174.010���� General rule for"
"[1973 c.439 �1; 1991 c.671 �3]"
"192 � Records; Public Reports and Meetings"
```

Those replacement characters are non-breaking spaces (`0xA0`), section symbols
(`§`) and em dashes (`—`). Decoding is now driven by the declared charset with
a Windows-1252 fallback, and the encoding used is recorded per chapter.

This mattered for more than cosmetics: the non-breaking spaces are the
separator between a section number and its catchline, so the corruption was
also destroying the main segmentation signal.

## Bold is the section anchor; line position is not

The first probe's counts looked like this, and they are the reverse of what
the naming suggested:

| chapter | lines opening with a section number | strict "anchors" | ambiguous |
|---|---|---|---|
| 192 | 287 | 3 | 284 |
| 279A | 125 | 7 | 118 |
| 646A | 417 | 4 | 413 |

The three to seven "anchors" were **not** section headings. They were wrapped
citation lines:

```
192.411 (2) within seven days after issuance of the order, or did not institute
279A.050 (6) may delegate authority to contract for and manage public contracts
646A.745 (1)(a), there is a rebuttable presumption that:
```

The hundreds of "ambiguous" lines were the real headings, missed only because
the separator is a non-breaking space rather than ordinary whitespace:

```
192.001    Policy concerning public records
279A.005  Short title
646A.005  Definitions
```

Two rules follow. A section number followed by `(` is a wrapped subsection
citation, never a heading. A section number followed by `[` is a heading only
when the bracket opens a disposition keyword — `[Repealed by ...]` — and is a
wrapped source credit when it opens a year, as in `279B.405 [2003 c.794 §2;`.

Even with those fixed, line position over-counts, because **each chapter opens
with a table of contents that repeats every section number and catchline**.
The contents entries are not bold; the body headings are. Chapter 192 has 343
bold runs against roughly 204 credits, consistent with bold marking body
sections.

**Segmentation for increment 2 anchors on bold runs, not on line position.**
The fixture at `tests/fixtures/word_export_chapter.html` reproduces this: six
line-level anchors, three bold anchors, three actual body sections.

## Source credits parse cleanly

Credits are dense and well formed, and they wrap across lines:

```
[1961 c.160 §2; 1965 c.302 §1; 1983 c.620 §11; 1989 c.16 §1; 1999 c.55 §1;
 1999 c.140 §1; 2011 c.645 §1; 2023 c.35 §2]
[Repealed by 1973 c.794 §34]
[Amended by 1961 c.160 §4; repealed by 1973 c.794 §34]
[Formerly 646.185; repealed by 2009 c.170 §4]
```

Counts are healthy: 204 credits in chapter 192, 205 in 646A, 55 in 279A. Four
credit forms are visible already — plain enactment, `Repealed by`, `Amended
by`, and `Formerly` for a renumbering — which maps directly onto the `action`
column in `ors_source_credit`.

## The edition year is on the chapter pages

Each chapter document prints its edition as two adjacent lines, `2025` then
`EDITION`, and names itself as `192 — Records; Public Reports and Meetings`.
So `edition_year` and `chapter_name` are both recoverable per chapter, and do
not depend solely on the index page.

## Chapters advertise pending changes

Chapter documents carry a notice naming the session that has changed them and
the Oregon Laws chapters involved:

```
ORS sections in this chapter were amended or repealed by the Legislative
Assembly during its 2026 regular session. See the table of ORS sections
amended or repealed during the 2026 regular session: 2026 A&R Tables

New sections of law were enacted ... See sections in the following 2026
Oregon Laws chapters: 2026 Session Laws 0011; 0017; 0085; 0096
```

This is a direct, printed join to the amendment parser's `(year, chapter)`
output, and it tells us the published 2025 edition is already behind the 2026
session. A future `ors_chapter_pending_change` table should capture it. It is
recorded here rather than acted on now, so increment 2 stays scoped.

## Still unresolved

The index page at `/bills_laws/pages/ors.aspx` yields no chapter roster. The
chapter URL pattern is confirmed independently, so this is a discovery problem
and not an acquisition problem. Diagnostics — page title, anchor and script
counts, href path-prefix histogram and sample hrefs — are now printed
immediately before the gate so the next run answers it.
