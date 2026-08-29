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

## The landing page does not publish a chapter roster

The page at `/bills_laws/pages/ors.aspx` is served by SharePoint and is the
right page — `Bills and Laws Oregon Revised Statutes`, 415 hrefs across 397
anchors, with its links present in the served HTML rather than built from
script.

Its largest path-prefix group is `bills_laws/ors` with 115 links, which looked
like the chapter roster. It is not. Listing every basename under that prefix
settled it:

- **87 session reference PDFs**, `1941.pdf` through `2025.pdf`, including
  special sessions (`1957ss.pdf`, `2002ss1.pdf` … `2002ss5.pdf`,
  `2020ss1.pdf` … `2020ss3.pdf`). These are the amendment-and-repeal tables
  the amendment effort already cites.
- **`OCLA.pdf`**, Oregon Compiled Laws Annotated.
- **28 General Index files**, `generalIndexA.pdf` through `generalIndexZ.pdf`
  plus `generalIndexPreface.pdf` and `generalIndexQuickSearch.pdf` — the
  alphabetical subject index.

There is not one chapter document among them. No amount of adjusting the href
matcher would have found a roster on this page, because the page does not
carry one.

Three diagnostic rounds were spent narrowing this, each answering slightly
less than the question needed: an alphabetical sample that never reached the
prefix, a per-prefix sample too small to be conclusive, and a JSON dump too
tall to survive the log tail. The lesson is recorded because it is the same
one the probe teaches: when a bounded sample cannot settle a question, list
the whole thing.

## ORS_TitlesChapters.pdf is a table of titles, not a chapter roster

The landing page links `/bills_laws/BillsLawsEDL/ORS_TitlesChapters.pdf`, and
its name suggested a per-chapter roster. It is not. Tika extracts:

```
TABLE OF TITLES
xxxv
COURTS
ORCP
Volume 1
Title 1 Courts of Record; Court Officers; Juries – Chs. 1-10
2 Procedure in Civil Proceedings – Chs. 12-25
5 Small Claims Department of Circuit Court – Ch. 46
BUSINESS
ORGANIZATIONS
Volume 2
Title 7 Corporations and Partnerships – Chs. 56-70
```

It lists volumes and titles with the chapter **range** each title covers. It
never enumerates chapters.

Four properties of the layout matter:

- Only the first title in each volume carries the word `Title`. The rest are
  bare leading numbers, so a pattern that treats a bare leading number as a
  chapter reads every continuation line as one. The first parser did exactly
  that and produced 41 fabricated chapters — which were title numbers. The
  edition-identity check is the only thing that caught it, which is precisely
  the failure the review finding on `editionId` predicted.
- Sidebar labels (`COURTS`, `ORCP`, `LANDLORD-`, `PROBATE`) and roman page
  numbers are interleaved with the entries. Requiring the dash-and-range
  suffix separates a title line from them.
- Ranges are printed with an en-dash and use `Ch.` for a single chapter.
- A title name too long for one line **wraps**, leaving the number and the
  start of the name on one line and the rest plus the range on the next.

## The wrapped title that vanished

The first run against the real document reported 21 volumes, 56 titles and
zero unparsed lines, which looked clean. It was not. Between title 18
(chs 176-185) and title 20 (chs 201-215) there was a gap: title 19,
`Miscellaneous Matters Related to Government and Public Affairs`, covering
chapters 190-200. Its name wraps, so neither half matched, and the title was
dropped in silence.

Nothing in the output said so. The loss surfaced only because chapter 192 is
in the development sample and could not be attributed to any published title,
which failed acquisition. The range check caught a parser defect it was not
written to catch.

Two things follow. Wrapped entries are now joined across lines. And a
number-led line that never resolves into a title is reported as
`unresolvedTitleLineCount`, gated at zero, so the next parser gap announces
itself instead of silently shrinking the roster.

## Lettered titles and lettered ranges both occur

The real document settles a question left open earlier. Range endpoints do
carry letters, and so do title numbers:

```
vol 7  title 26A  chs 284-285C  Economic Development
vol 7  title 27   chs 286A-289  Public Borrowing
vol 13 title 36A  chs 455-470   Housing; Lottery and Games; Environment
vol 14 title 37   chs 471-475C  Alcoholic Liquors; Controlled Substances; Drugs
```

Sort-key containment handles these: chapter 285B falls inside 284-285C, and
279A falls inside the numeric range 276-283.

## What the document does give

`ors_volume` and `ors_title` rows, populated from the authoritative source:
volume number, title number, title name, and the chapter span each covers.

The ranges are also load-bearing as a check. Their gaps are real: title 1
covers chapters 1-10 and title 2 covers 12-25, so chapter 11 does not exist;
title 8 ends at 84 and title 9 begins at 86, so neither does 85. A chapter
named from anywhere else can be tested against the published ranges, and one
falling under no title is rejected before it is fetched. Sort-key containment
means a lettered chapter such as 90A correctly falls inside a printed 90-105.

The document carries no edition banner, so `editionId` cannot come from it.
The chapter documents print `2025` / `EDITION`, so edition identity is
established there instead — before any row is emitted, not before a source is
acquired.

## Still unresolved: the chapter roster

No published document found so far enumerates ORS chapters. Chapters are
currently named explicitly, by the fixed development sample, and validated
against the published title ranges.

The natural next step is discovery by verified enumeration: walk each
published title range, fetch each candidate chapter document, and record a
200 with its digest as a chapter and a 404 as an absence. That is not
guessing — every chapter in the resulting roster would be backed by a
retrieved document, and every gap by a recorded response.

Lettered chapters are no longer an obstacle: the ranges express them
directly, so a range such as 284-285C states its own letter span. It remains
a whole-edition operation of several hundred requests, so it belongs in its
own increment rather than in this one.

## The other Legislative Counsel documents

`ORS_Renum.pdf` is a renumbering table bearing on `ors_section.renumbered_to`,
and `ORS_Preface.pdf` accompanies the edition. Both are noted for later
increments.
