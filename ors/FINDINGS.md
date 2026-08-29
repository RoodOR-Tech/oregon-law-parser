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

  ch 1     title 1   102 sections  Courts and Judicial Officers Generally
  ch 90    title 10  169 sections  Residential Landlord and Tenant
  ch 161   title 16  109 sections  General Provisions
  ch 174   title 17   28 sections  Construction of Statutes; General Definitions
  ch 192   title 19  166 sections  Records; Public Reports and Meetings
  ch 279A  title 26   53 sections  Public Contracting - General Provisions
  ch 646A  title 50  265 sections  Trade Regulation

Problems: 0   Integrity violations: 0
Foreign anchors: 0   Chapters with no name: 0
```

Chapter names took one further fix, for the same reason the banner had. The
heading prints the word `Chapter` above the number and name, and the source
newline between them means the parser sees `Chapter 192 – Records; Public
Reports and Meetings` as one logical line. The prefix is now optional in the
heading pattern, and every chapter's name and owning title come through.

`chapter_name` is a schema column, so a chapter without one is a gap rather
than a nullable convenience. It is now gated, and a chapter that cannot find
its heading reports the lines that mention its number.

Every status came back `operative` on this run. That is expected for the
sample rather than reassuring: the repeal and renumbering stubs the probe
counted (138 in chapter 646A alone) are printed unbolded in these documents,
so bold anchoring does not reach them. Capturing them belongs with the notes
and credits work in increment 3.

## Source credit forms beyond FINDINGS.md's first sample

Increment 3's `unparsedCreditSegmentCount` diagnostic — gated at zero the same
way `unresolvedTitleLineCount` and `chaptersWithoutName` are — did its job on
its first real run: 103 segments across the seven sample chapters matched
none of the forms recorded above. All ten distinct real forms behind that
count are now handled:

**Numbered special sessions.** The bare `s.s.` marker recorded earlier is the
pre-2000s convention. Since 2002 the marker names which special session, with
no space before the digit:

```
2002 s.s.1 c.10 §7
2020 s.s.3 c.3 §11
```

`special_session` now records the ordinal (`1`, `3`) rather than a bare
1-or-null flag, and the pre-2000s bare form still records `1` since it names
a special session without an ordinal.

**Plural-section citations.** A doubled section mark cites more than one
section under one `(year, chapter)`:

```
2013 c.154 §§2,3
1999 c.676 §§7,7a
```

Each becomes its own `ors_source_credit` row — same year, chapter and raw
segment, one row per section number — so every row still joins to exactly one
amendment-parser section rather than one row trying to hold two.

**A trailing parenthetical annotation.**

```
2001 c.823 §25 (enacted in lieu of 8.172)
```

The citation itself still parses; the annotation is kept in `raw_credit` but
not otherwise modeled. What "in lieu of" relationships mean for the relational
model, if anything beyond this, is left to a later increment.

**A fourth action keyword.** `reenacted by 1997 c.196 §3` — `SCHEMA.md`'s
closed action set has no `reenacted` value, so this keyword maps to `enacted`:
it states the session law (re-)established the section, which is what
`enacted` already means in that set.

**A renumbering note carrying a year.** `renumbered 1.179 in 2025` extends the
bare `Renumbered NNN.NNN` form with when the renumbering happened. The year is
discarded rather than parsed as a session-law year: the segment does not state
that session as the one that did the renumbering, only the year it occurred.

None of these were guessable from the first sample; each is exactly what
`unparsedCreditSegmentCount` exists to surface rather than let disappear as
silently-dropped rows.

## A second round of unparsed forms

Fixing the ten forms above did not reach zero: the next CI run against the
same seven sample chapters reported 6 remaining unparsed segments, all
visible in a single log read now that the diagnostic cap is 500 rather than
10. Six more real forms, none guessable from the first two samples:

**Two citations joined by "and" instead of a semicolon.**

```
2009 c.431 §6 and 2009 c.816 §15
1999 c.603 §2b and 1999 c.676 §4
```

Tried only after a segment fails to parse outright as one citation, and only
accepted when the split yields exactly two parts that both independently
parse as citations — so a segment that merely contains the word "and" for
some other reason (an unresolved cross-reference note, say) still falls
through to `unparsedSegments` rather than being torn in half.

**A fifth action keyword, phrased with "from" rather than "by".**

```
Derived from 1983 c.740 §1
```

Maps to `enacted`, same as `reenacted by`: it states the session law that
established the section, without using "by".

**A citation scoped to one subsection.**

```
subsection (3) enacted as 1961 c.150 §5
```

The prefix is read past to reach the citation underneath; which subsection is
not modeled, since `ors_source_credit` is scoped to whole sections (see
SCHEMA.md's deferred list). The citation itself still becomes a normal
`enacted` row.

**`Formerly` naming a subsection range instead of the whole destination
section.**

```
Formerly subsections (1) to (3) of 192.450
```

`formerly_references` still records `192.450` — the qualifier narrows which
part of the destination, not which section it is, so it is read past the
same way the subsection-scoped citation prefix is.

**One section cited with more than one of its subsections**, as distinct from
the plural-*section* `§§2,3` form already handled:

```
1977 c.517 §8(2),(3)
```

Here `(2)` and `(3)` are subsections of the single cited section §8, not two
more sections — a list item with no leading digit continues the previous
item's section number rather than naming one of its own. This became a
one-row citation for section `8`, matching the earlier plural-section list
parser's structure without conflating the two forms: `§§2,3` genuinely means
two sections, `§8(2),(3)` genuinely means one.

With all six of these handled, `unparsedCreditSegmentCount` reached zero
against the sample chapters. Subsection-level detail — which subsection an
"enacted as" or `(2),(3)` scoping names — is intentionally not modeled in the
current schema; see `ROADMAP.md` for that as explicit future work rather than
a silently dropped distinction.

## A third round, caused by fixing the second

The round-2 fix tightened the trailing-parenthetical pattern to exclude a
leading digit, specifically so it would not be mistaken for a subsection-list
continuation such as `(3)` in `§8(2),(3)`. That exclusion was never actually
needed -- the subsection-list group is greedy and already consumes a true
`(2),(3)` continuation on its own -- and it broke a real annotation form the
next CI run surfaced, 5 times across chapters 90 and 161:

```
repealed by 2001 c.596 §25 (90.771 enacted in lieu of 90.770)
repealed by 1977 c.380 §10 (161.336 enacted in lieu of 161.335)
repealed by 1977 c.380 §12 (161.341 enacted in lieu of 161.340)
repealed by 1977 c.380 §14 (161.346 enacted in lieu of 161.345)
repealed by 1977 c.380 §16 (161.351 enacted in lieu of 161.350)
```

Here the annotation's own first token is a dotted section number, so a
leading-digit exclusion rejects it along with the genuine subsection
continuation it was meant to guard against. The fix was to drop the
exclusion: `CREDIT_CITATION_PATTERN`'s trailing parenthetical now accepts any
content, relying on the subsection-list group already having first claim on
anything shaped like `(2)` or `(3)` earlier in the pattern. A tightening
added to handle one form is not free just because it passes the sample it
was written against -- it can silently break a sibling form the very next
real chapter shows, which is why every fix in this project is re-verified
against every previously-established form before it is pushed, not just the
form that motivated it.

## Re-examining the "138 stubs" figure

The first clean run's note that every section came back `operative` pointed
at the probe's `repealStubMatches` count (138 for chapter 646A) as the size
of the gap. That count is not what it was taken for: `REPEAL_STUB_PATTERN`
matches `\[(?:Repealed|Renumbered|Amended|Formerly)\b` anywhere in the whole
document, with no requirement that the bracket be the entirety of a section's
entry. An ordinary operative section whose own credit happens to read
`[Formerly 646.185; repealed by 2009 c.170 §4]` matches it too, and that
section already has a bold catchline, a body, and a correctly parsed
`ors_source_credit` row -- it is not missing anything. 138 is an upper bound
on printed brackets starting with those words, not a count of unanchored
sections.

The real question is how many lines are shaped like `parse_ors_chapter.py`'s
own `SECTION_STUB_PATTERN` -- a section number immediately followed by the
bracket, with nothing else on the line -- and fall outside every bold span
already found. `find_unbolded_stub_lines` measures exactly that, reported as
`unboldedStubLineCount` and a per-line sample, diagnostic only for now.

Run against the real sample chapters, the answer was zero: no stub-shaped
line, under the keyword-led pattern that existed at the time, sat outside a
bold span. Every disposition stub in the sample is bold after all -- the
same anchoring convention as an ordinary catchline heading.

## The pattern itself was too narrow, not the anchoring

Zero unbolded stubs did not mean zero missing sections. `statusCounts` on
that same run still showed every one of the 892 sections as `operative`,
and a line already visible in an earlier CI run's structure-probe sample for
chapter 1 explains why:

```
1.055 [1959 c.638 §1; repealed by 2015
```

(cut off mid-bracket in that view because the probe treats a source newline
as a line break; the parser's rejoined logical-line view sees the whole
bracket as one line.) This is a stub-only section -- no catchline, no body,
printed like any other disposition stub -- but its bracket opens with a
plain enactment citation, `1959 c.638 §1`, and states the repeal as a later
segment rather than leading with a keyword. `SECTION_STUB_PATTERN` required
the keyword to lead the bracket, so this form matched neither the catchline
pattern (no capital letter after the number) nor the stub pattern (no
keyword after the number): it anchored nothing at all and produced no row.

`classify_stub` already finds the disposition keyword wherever it falls in
the bracket text, not only at its start, so it needed no change. The fix was
to the anchor-shape pattern itself: a section is stub-only whenever the
entire remainder of its line after the number is exactly one bracket,
regardless of what opens it. The same broadening was applied to the
unbolded-line diagnostic, with one added guard: a number already claimed by
a bold anchor is never reported there again, since the broader pattern could
otherwise mistake a contents-list echo of an already-found stub for a new
one, the exact risk bold anchoring exists to avoid for catchline headings.

The lesson generalizes past this one pattern: a rule proven against the
first few real forms it was written for is not proven against forms it
hasn't seen yet, and "which sections come back non-operative" is exactly the
kind of downstream signal -- like `unparsedCreditSegmentCount` before it --
that catches a pattern too narrow for real data.

## The other Legislative Counsel documents

`ORS_Renum.pdf` is a renumbering table bearing on `ors_section.renumbered_to`,
and `ORS_Preface.pdf` accompanies the edition. Both are noted for later
increments.
