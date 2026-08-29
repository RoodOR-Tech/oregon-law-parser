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
- A title entry too long for one line **wraps**, in either of two places: the
  name may break, carrying the dash and range onto the next line; or the break
  may fall after the dash, leaving `Chs. 190-200` alone on its own line.

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

That diagnostic immediately earned itself. Handling only the first wrap form
raised the count from 56 titles to 58 but left two entries unresolved, and
the gate named them exactly:

```
Unresolved title lines: 2
  unresolved: 19 Miscellaneous Matters Related to Government and Public Affairs –
  unresolved: Title 45 Water Resources: Irrigation, Drainage, Flood Control, Reclamation –
```

Both break after the dash rather than inside the name, leaving the range
alone on the following line. Without the diagnostic those two titles would
have gone missing as quietly as the first one did — and title 19, covering
chapters 186-200, is the one that carries chapter 192.

Handling both forms brought the count to its final 60 titles with nothing
unresolved.

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

## The parsed result

The 2025 table of titles yields **21 volumes and 60 titles**, with zero
unparsed and zero unresolved lines:

```
vol 1   title 1    chs 1-10      Courts of Record; Court Officers; Juries
vol 5   title 19   chs 186-200   Miscellaneous Matters Related to Government and Public Affairs
vol 7   title 26A  chs 284-285C  Economic Development
vol 15  title 45   chs 536-558   Water Resources: Irrigation, Drainage, Flood Control, Reclamation
vol 19  title 62   chs 835-838   Aviation
```

Title numbers are not contiguous — 15, 19A, 39, 40, 55 and 60 are absent —
and neither are the chapter ranges. Both gaps are real and are preserved.

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

## Chapter documents vary in their front matter

The chapters sampled first — 192, 279A, 646A — open directly with their own
heading and edition banner:

```
Oregon Revised Statutes
Chapter
192 – Records; Public Reports and Meetings
2025
EDITION
```

Chapter 1 does not. It opens its title, so the document carries the title's
front matter first:

```
TITLE
1
COURTS
OF RECORD; COURT OFFICERS; JURIES
Chapter 1. Courts and
Judicial Officers Generally
2. Supreme
Court; Court of Appeals
```

That list is the title's chapters, not this chapter's sections, and it pushes
both the chapter heading and the edition banner past any small head window.
Searching a fixed number of leading lines therefore found neither, and since
edition identity gates row emission, the whole chapter produced nothing.

The edition banner is now searched for across the whole document, and the
chapter heading is searched for by the expected chapter number, so front
matter cannot hide it and another chapter's heading is never accepted in its
place.

## Bold anchoring holds on real documents

Measured on the sample, with a chapter's own catchlines coming through
cleanly:

```
646A  1,341,520 bytes  12,152 lines  560 section numbers
      320 line anchors   265 bold anchors   205 credits   138 stubs

chapter 1 bold anchors:
  1.001 State policy for courts.
  1.002 Supreme Court; Chief Justice as administrative head of judicial department; ...
  1.005 Credit card transactions for fees, security deposits, fines and ...
```

A bold run naming another chapter's section is a bolded citation, not a
heading. Those are counted as `foreignAnchorCount` and skipped rather than
failing the run: they are not this chapter's rows, and a chapter is not
defective for citing another.

## Source newlines, and why the edition banner went missing

Every chapter of the sample reported "states no ORS edition year", including
the ones whose banner the probe had plainly shown. The cause is a difference
between two reasonable ways to decide what a line is.

The published banner puts a literal newline between the year and the word,
with no tag between them:

```html
<p class=MsoNormal align=center><b><span style='font-size:14.0pt'>2025
EDITION<o:p></o:p></span></b></p>
```

The probe treats a source newline as a line break, so it reported `2025` and
`EDITION` as adjacent lines. The parser deliberately rejoins wrapped text into
logical lines, because statutory text wraps constantly in these exports and a
sentence split across source lines is still one sentence. The same banner
therefore arrives at the parser as the single line `2025 EDITION`.

Neither behaviour is wrong; reading only the two-line form was. The banner is
now read in either shape. The wider lesson is that "line" is not a shared
concept between the two tools, so a rule proven on the probe's output does not
transfer to the parser unexamined.

## The parser's first clean run on real chapters

Once the banner was read in its logical-line shape, the seven sample chapters
produced rows with nothing outstanding:

```
Editions: 1   Chapters: 7   Subdivisions: 146   Sections: 892
  ch 1     title 1   102 sections
  ch 90    title 10  169 sections
  ch 161   title 16  109 sections
  ch 174   title 17   28 sections
  ch 192   title 19  166 sections
  ch 279A  title 26   53 sections
  ch 646A  title 50  265 sections
Problems: 0   Integrity violations: 0   Foreign anchors: 0
```

Chapter names were still empty, for the same reason the banner had been. The
heading prints the word `Chapter` above the number and name, and the source
newline between them means the parser sees `Chapter 192 – Records; Public
Reports and Meetings` as one logical line. The prefix is now optional in the
heading pattern.

`chapter_name` is a schema column, so a chapter without one is a gap rather
than a nullable convenience. It is now gated, and a chapter that cannot find
its heading reports the lines that mention its number.

Every status came back `operative` on this run. That is expected for the
sample rather than reassuring: the repeal and renumbering stubs the probe
counted (138 in chapter 646A alone) are printed unbolded in these documents,
so bold anchoring does not reach them. Capturing them belongs with the notes
and credits work in increment 3.

## The other Legislative Counsel documents

`ORS_Renum.pdf` is a renumbering table bearing on `ors_section.renumbered_to`,
and `ORS_Preface.pdf` accompanies the edition. Both are noted for later
increments.
