#!/usr/bin/env python3
"""Parse acquired ORS chapter documents into relational rows.

Stage 4 of the ORS relational-table pipeline. Emits ors_edition, ors_chapter,
ors_subdivision and ors_section rows from the chapter documents acquired by
acquire_ors_chapters.py.

Segmentation follows what the probe measured rather than what the layout
suggests. The sources are Windows-1252 Word HTML exports with no semantic
markup, and each chapter opens with a table of contents repeating every
section number and catchline. Those contents entries are not bold; the body
headings are. Sections are therefore anchored on bold runs, not on line
position, which over-counts by roughly a factor of two.

Every row carries character offsets into the normalized chapter text, so any
row traces back to the exact span of pinned source bytes that produced it.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ors_chapters import chapter_sort_key, parse_chapter_number  # noqa: E402
from ors_credits import parse_source_credit  # noqa: E402
from ors_cross_references import (  # noqa: E402
    find_cross_reference_candidates,
    resolve_cross_references,
)
from ors_pending_changes import find_pending_change_notices  # noqa: E402
from ors_section_notes import find_editorial_note_candidates, split_editorial_notes  # noqa: E402
from ors_text import decode_markup, declared_charset, normalize_spaces  # noqa: E402

SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]*>")
# Tags that end a visible line in the published exports.
BLOCK_BOUNDARY_PATTERN = re.compile(
    r"^</?\s*(?:br|p|div|tr|li|h[1-6]|table|blockquote)\b", re.IGNORECASE
)
BOLD_OPEN_PATTERN = re.compile(r"^<\s*b\b", re.IGNORECASE)
BOLD_CLOSE_PATTERN = re.compile(r"^<\s*/\s*b\b", re.IGNORECASE)

# A section heading: number then catchline. An opening parenthesis marks a
# wrapped subsection citation instead, so it is excluded. A catchline that
# defines a term also opens by quoting that term -- 105.850's own "“Commercial
# property” defined for ORS 105.850 to 105.870." is the real form that
# surfaced this, confirmed against chapter 105's gold review -- so an opening
# quotation mark is accepted here alongside a capital letter, not only the
# capital letter of an ordinary sentence-initial catchline.
SECTION_CATCHLINE_PATTERN = re.compile(
    r"^(?P<number>\d{1,3}[A-Z]?\.\d{3})\s+(?=[A-Z“‘\"'])(?P<catchline>.*)$"
)
# A section printed only as a bracketed history: nothing else appears on the
# line after the number. A keyword leading the bracket ("[Repealed by ...]")
# is one real form; a plain enactment citation whose own later segment
# states the disposition is another -- "1.055 [1959 c.638 §1; repealed by
# 2015 c.629 §1]" was observed directly in chapter 1's own structure-probe
# sample, printed with no catchline and no body at all. classify_stub already
# finds the disposition keyword wherever it falls in the bracket, not only at
# its start, so one pattern serves both forms. Requiring the entire
# post-number remainder to be exactly one bracket -- nothing before it,
# nothing after -- is what tells a stub apart from a catchline (which starts
# with a capital letter, never "[") and from an ordinary section whose body
# ends in a trailing credit (which has statutory text before the bracket).
SECTION_STUB_PATTERN = re.compile(
    r"^(?P<number>\d{1,3}[A-Z]?\.\d{3})\s+(?P<stub>\[[^\[\]]*\])\s*$"
)
# The real published form for a stub-only section, confirmed by dumping raw
# markup directly (find_embedded_stub_markup_samples): the number is bold on
# its own, and its bracket is a *separate*, non-bold span immediately after
# it in the same paragraph --
#   <b><span>      1.055</span></b><span> [1959 c.638 §1; repealed by 2015
#   c.212 §2]</span>
# Neither SECTION_CATCHLINE_PATTERN nor SECTION_STUB_PATTERN matches this,
# since both require the catchline or bracket to appear inside the *same*
# bold run; a bold run containing only the number matches neither and was
# silently dropped as a non-anchor, which is why two rounds of fixing
# normalize_chapter_text's newline handling both measured zero change --
# neither one was the real bug.
BARE_NUMBER_PATTERN = re.compile(r"^(?P<number>\d{1,3}[A-Z]?\.\d{3})$")
FOLLOWING_STUB_PATTERN = re.compile(r"^\s*(?P<stub>\[[^\[\]]*\])")
# A literal source newline immediately followed by a new stub entry's
# opening. See _collapse_internal_newlines's docstring: this is what tells a
# real break between consecutive stub-only entries apart from an ordinary
# wrapped-prose newline, which must still collapse to a space.
STUB_LINE_BREAK_PATTERN = re.compile(r"\n(?=\s*\d{1,3}[A-Z]?\.\d{3}\s*\[)")
_NEWLINE_PLACEHOLDER = "\x00"
# Whether a run of text opens a new stub entry, used to look past a purely
# whitespace inter-tag run into the next real content -- see
# normalize_chapter_text's upcoming_run_opens_a_stub.
STUB_ENTRY_OPEN_PATTERN = re.compile(r"^\d{1,3}[A-Z]?\.\d{3}\s*\[")
# A trailing bracketed group is the section's source credit. Parsing its
# contents into rows is increment 3; here it is only separated from the
# statutory text so body_text holds the text and not the history.
#
# The credit is not always the literal last thing printed: a real section
# sometimes carries an editorial "Note:"/"Notes:" block immediately after
# its own credit instead of nothing (see ors_section_notes.py's module
# docstring for the real forms; 2025-1.002's "... 2025 c.256 §6] Note:
# Sections 3 and 4, chapter 88, ..." is the fragment that surfaced this).
# Requiring the bracket to reach the true end of the string missed the
# credit entirely for every such section -- it never became a source-
# credit row at all, silently staying merged into body_text along with its
# note. The lookahead also accepts a bracket immediately followed by a
# note introducer, so the credit is still recognized as one.
TRAILING_CREDIT_PATTERN = re.compile(r"(?P<credit>\[[^\[\]]*\])\s*(?=$|Notes?:\s)")
RENUMBERED_TO_PATTERN = re.compile(r"\bRenumbered\s+(?P<number>\d{1,3}[A-Z]?\.\d{3})", re.IGNORECASE)

# The chapter document names itself as "192 - Records; Public Reports and
# Meetings" and prints its edition as "2025" followed by "EDITION".
# The heading is printed as the word "Chapter" above the number and name. A
# source newline between them, like the one in the edition banner, means the
# parser sees them rejoined as one logical line, so the prefix is optional.
CHAPTER_HEADING_PATTERN = re.compile(
    r"^(?:Chapter\s+)?(?P<number>\d{1,3}[A-Z]?)\s*[–—-]\s*(?P<name>\S.*)$",
    re.IGNORECASE,
)
EDITION_YEAR_PATTERN = re.compile(r"^((?:19|20)\d{2})$")
# The banner is printed as a year line above an EDITION line, but a layout
# that keeps them on one line must read the same.
EDITION_BANNER_PATTERN = re.compile(r"^((?:19|20)\d{2})\s+EDITION\b", re.IGNORECASE)
# Any bare year line, used only to explain a failure to find the banner.
BARE_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")

# Centred headings dividing a chapter carry no section number. They appear as
# an all-capitals run or as a parenthesized phrase.
UPPER_HEADING_PATTERN = re.compile(r"^[A-Z][A-Z0-9 ,.;:'&/–—-]{2,}$")
PAREN_HEADING_PATTERN = re.compile(r"^\([A-Z][^()]{2,}\)$")
SECTION_NUMBER_ANYWHERE = re.compile(r"\d{1,3}[A-Z]?\.\d{3}")

# How far into a document to look for a chapter heading when the expected
# chapter number is unknown. A chapter that opens a title carries that title's
# front matter first -- chapter 1's document begins "TITLE / 1 / COURTS / OF
# RECORD; COURT OFFICERS; JURIES" and then lists the title's chapters -- so a
# small window misses both the heading and the edition banner. When the
# expected number is known the whole document is searched for that number, and
# the edition banner is always searched for in full.
HEAD_LINE_LIMIT = 40


def iter_runs(markup):
    """Yield (text, is_bold) runs, with block boundaries as newline runs.

    Bold state is tracked across the document so a section heading split into
    several bold spans is still recognized as one run of bold text.
    """
    markup = SCRIPT_STYLE_PATTERN.sub(" ", markup)
    bold_depth = 0
    cursor = 0
    for match in TAG_PATTERN.finditer(markup):
        chunk = markup[cursor:match.start()]
        if chunk:
            yield chunk, bold_depth > 0
        cursor = match.end()
        tag = match.group(0)
        if BOLD_OPEN_PATTERN.match(tag):
            bold_depth += 1
        elif BOLD_CLOSE_PATTERN.match(tag):
            bold_depth = max(0, bold_depth - 1)
        elif BLOCK_BOUNDARY_PATTERN.match(tag):
            yield "\n", bold_depth > 0
    tail = markup[cursor:]
    if tail:
        yield tail, bold_depth > 0


def _collapse_internal_newlines(text):
    """Collapse a wrapped-prose newline to a space, but keep a real line
    break immediately before a new stub entry ("NNN.NNN [...]").

    Ordinary statutory text wraps across source lines constantly, and a
    sentence split that way must rejoin as one line -- the same principle
    behind reading "2025\\nEDITION" as one logical line elsewhere in this
    module. But a run of disposition-only stub entries prints with only a
    literal source newline between consecutive entries and no separating
    tag: "1.165 [1981 s.s. c.3 §7; renumbered 1.185 in 1999]\\n1.167 [...]".
    Collapsing that newline the same way as ordinary prose silently merged
    every stub after the first into the *previous* section's body text,
    which is why `unboldedStubLineCount` measured zero against the real
    sample chapters despite real stub-only sections being present in them:
    none of them ever became their own line for `SECTION_STUB_PATTERN` to
    test against. A newline directly followed by a stub-shaped opening is
    therefore kept as a real line break instead.
    """
    protected = STUB_LINE_BREAK_PATTERN.sub(_NEWLINE_PLACEHOLDER, text)
    collapsed = protected.replace("\n", " ")
    return collapsed.replace(_NEWLINE_PLACEHOLDER, "\n")


def normalize_chapter_text(markup):
    """Build the normalized chapter text and the bold spans within it.

    Returns (text, bold_spans) where each span is a (start, end) pair into
    text. Whitespace inside a run is collapsed and block boundaries become
    single newlines, so offsets are stable for a given source document.
    """
    runs = list(iter_runs(markup))
    pieces = []
    bold_spans = []
    length = 0
    open_bold = None

    def append(fragment):
        nonlocal length
        if not fragment:
            return
        pieces.append(fragment)
        length += len(fragment)

    def upcoming_run_opens_a_stub(index):
        """Whether the next real content past this point starts a new stub.

        A whitespace-only run between two tags (e.g. each stub entry wrapped
        in its own bare <span>, with the literal newline living *between*
        the tags rather than inside either one's text) cannot answer this
        from its own content alone: the number and bracket are in a later
        run entirely. Looking ahead past any further whitespace-only runs to
        the next real content is what a single-run lookahead like
        `_collapse_internal_newlines` cannot do, and is the difference
        between "1.160 ... statutes.\\n1.165 [...]" being read as one
        section's body versus two: see FINDINGS.md for how the first
        attempt at this fix, correct for a newline inside one run, still
        measured zero on real chapters because their stub entries are
        span-wrapped this way.
        """
        for later_raw, _ in runs[index + 1:]:
            if later_raw == "\n":
                continue
            candidate = normalize_spaces(html.unescape(later_raw)).lstrip()
            if not candidate:
                continue
            return bool(STUB_ENTRY_OPEN_PATTERN.match(candidate))
        return False

    for index, (raw, is_bold) in enumerate(runs):
        # The bold transition is handled before anything else. Handling it
        # only for text runs let two adjacent bold headings separated by a
        # block boundary merge into a single span, which silently swallowed
        # the second section.
        if is_bold and open_bold is None:
            open_bold = length
        elif not is_bold and open_bold is not None:
            bold_spans.append((open_bold, length))
            open_bold = None
        if raw == "\n":
            if pieces and not pieces[-1].endswith("\n"):
                append("\n")
            continue
        text = normalize_spaces(html.unescape(raw))
        if not text.strip():
            # Whitespace between runs still separates words -- unless it
            # carries a literal newline immediately ahead of a new stub
            # entry, which must stay a real line break so that entry
            # becomes its own line for SECTION_STUB_PATTERN to test.
            if "\n" in text and upcoming_run_opens_a_stub(index):
                if pieces and not pieces[-1].endswith("\n"):
                    append("\n")
            elif pieces and not pieces[-1].endswith((" ", "\n")):
                append(" ")
            continue
        # text.strip() is already known non-empty here (the branch above
        # handles the empty case), and collapsing whitespace never removes
        # visible characters, so no further emptiness check is needed.
        text = re.sub(r"[ \t\r\f\v]+", " ", _collapse_internal_newlines(text))
        append(text)
    if open_bold is not None:
        bold_spans.append((open_bold, length))

    # Offsets are recorded against exactly this string, so it is returned
    # unaltered: any later rewrite would invalidate every span.
    return "".join(pieces), bold_spans


def line_spans(text):
    """Yield (line, start, end) for every non-empty line of the text."""
    offset = 0
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped:
            start = offset + (len(raw) - len(raw.lstrip()))
            yield stripped, start, start + len(stripped)
        offset += len(raw) + 1


def classify_stub(stub_text):
    """Return (status, renumbered_to) for a bracketed section stub.

    A stub can record more than one event, as in "[Amended by 1961 c.160 s.4;
    repealed by 1973 c.794 s.34]". The final disposition wins, so a repeal is
    reported even when an amendment precedes it.
    """
    lowered = stub_text.lower()
    renumbered = RENUMBERED_TO_PATTERN.search(stub_text)
    if "repealed" in lowered:
        return "repealed", None
    if "renumbered" in lowered:
        return "renumbered", renumbered.group("number") if renumbered else None
    if "reserved" in lowered:
        return "reserved", None
    # An amendment-only or formerly-only stub records history but no operative
    # text, so it is a note rather than an operative section.
    return "note_only", None


def split_source_credit(body):
    """Separate a trailing bracketed source credit from the statutory text.

    The credit itself is removed either way. A note block following it (see
    TRAILING_CREDIT_PATTERN's comment) is not statutory text either, but
    note extraction is not built yet, so it is kept rather than dropped --
    joined back onto the text ahead of the credit, the same body_text shape
    a section with no trailing note already has.
    """
    # The last such match, not the first: a note's own prose can mention a
    # session-law citation in passing (chapter 88, Oregon Laws 2025 was
    # already seen as one), and if that ever appeared in bracket form
    # ahead of a real trailing credit, .search()'s leftmost match would
    # seize on it instead of the section's actual credit.
    matches = list(TRAILING_CREDIT_PATTERN.finditer(body))
    if not matches:
        return body.strip(), None
    match = matches[-1]
    before = body[: match.start()].strip()
    after = body[match.end():].strip()
    if after:
        return (f"{before} {after}" if before else after), match.group("credit")
    return before, match.group("credit")


def parse_chapter_heading(lines, expected_number=None):
    """Read the chapter number and name the document prints for itself.

    When the expected chapter number is known the whole document is searched
    for a heading carrying that number, so front matter ahead of the heading
    does not hide it and a heading for some other chapter is never accepted.
    """
    fallback = None
    for index, (line, _, _) in enumerate(lines):
        match = CHAPTER_HEADING_PATTERN.match(line)
        if match is None:
            continue
        number = parse_chapter_number(match.group("number"))
        if number is None:
            continue
        name = match.group("name").strip()
        if expected_number is None:
            if index < HEAD_LINE_LIMIT:
                return number, name
            continue
        if number == expected_number:
            return number, name
        if fallback is None and index < HEAD_LINE_LIMIT:
            fallback = (number, name)
    return fallback if fallback is not None else (None, None)


def parse_edition_year(lines):
    """Read the edition the document prints, as a year line then EDITION.

    The whole document is searched. A chapter opening a title carries that
    title's front matter ahead of the banner, which put it out of reach of a
    fixed head window.
    """
    for index, (line, _, _) in enumerate(lines):
        banner = EDITION_BANNER_PATTERN.match(line)
        if banner is not None:
            return int(banner.group(1))
        match = EDITION_YEAR_PATTERN.match(line)
        if match is None:
            continue
        following = lines[index + 1][0] if index + 1 < len(lines) else ""
        if following.upper().startswith("EDITION"):
            return int(match.group(1))
    return None


def heading_diagnostics(lines, chapter_number):
    """Explain a failure to find the chapter's own heading.

    Reports the lines that mention the chapter number at all, plus a bounded
    sample of the opening lines, so a heading layout this parser does not
    understand is visible instead of leaving chapter_name silently null.
    """
    needle = f"{chapter_number} " if chapter_number else None
    mentions = []
    if needle:
        for line, _, _ in lines:
            if line.startswith(needle) or f"Chapter {chapter_number}" in line:
                mentions.append(line[:140])
            if len(mentions) >= 10:
                break
    return {
        "numberMentions": mentions,
        "sampleLines": [line[:120] for line, _, _ in lines[:30]],
    }


def edition_diagnostics(lines):
    """Explain a failure to find the edition banner.

    Reports every line naming the word EDITION together with its neighbours,
    and a bounded sample of the document's opening lines. A missing banner
    stops every row for a chapter, so the reason has to be legible from the
    report rather than inferred.
    """
    mentions = []
    for index, (line, _, _) in enumerate(lines):
        if "EDITION" not in line.upper():
            continue
        mentions.append({
            "previous": lines[index - 1][0][:120] if index else None,
            "line": line[:120],
            "next": lines[index + 1][0][:120] if index + 1 < len(lines) else None,
        })
        if len(mentions) >= 10:
            break
    return {
        "lineCount": len(lines),
        "editionMentions": mentions,
        "yearLikeLines": [
            line[:120] for line, _, _ in lines if BARE_YEAR_PATTERN.fullmatch(line)
        ][:10],
        "sampleLines": [line[:120] for line, _, _ in lines[:30]],
    }


def find_unbolded_stub_lines(lines, bold_spans, anchored_numbers):
    """Stub-shaped lines that bold-run anchoring does not reach.

    FINDINGS.md's first clean run recorded every section as `operative` and
    attributed that to disposition stubs printed unbolded, citing the probe's
    `repealStubMatches` count (138 for chapter 646A). That count is a looser
    measure than it looks: it matches any bracket anywhere in the document
    starting with one of these keywords, including an ordinary operative
    section's own credit ("[Formerly 646.185; repealed by ...]" on a section
    that has a bold catchline and body text already parsed correctly). It is
    not a count of missing sections. Measured directly against the real
    sample chapters, the true count was zero.

    `SECTION_STUB_PATTERN` was since broadened to match any bracket-only
    line, not only one led by a disposition keyword (see its own comment),
    which raises the same risk bold anchoring was built to avoid: the
    contents list at the head of a chapter repeats section entries unbolded,
    so a plain-citation-led stub could in principle be found twice -- once as
    the real body entry (bold, already anchored), once as its own unbolded
    contents-list echo. A number already claimed by a bold anchor is
    therefore never reported here, only a bracket-only line whose number
    was not anchored by anything.

    This is a measurement, not a fix: nothing here changes which sections
    are emitted, so the true scale of any remaining gap is seen before a
    rule is written for it, the same discipline that shaped every earlier
    diagnostic in this parser.
    """
    found = []
    for line, start, _ in lines:
        match = SECTION_STUB_PATTERN.match(line)
        if match is None:
            continue
        if match.group("number") in anchored_numbers:
            continue
        if any(bold_start <= start < bold_end for bold_start, bold_end in bold_spans):
            continue
        found.append({"number": match.group("number"), "line": line[:200]})
    return found


EMBEDDED_STUB_PATTERN = re.compile(r"(?P<number>\d{1,3}[A-Z]?\.\d{3})\s*\[")


def find_embedded_stub_markup_samples(markup, text, anchored_numbers, limit=10):
    """Raw markup bytes around a number immediately followed by a bracket
    that is not already a real anchor.

    Two rounds of fixing normalize_chapter_text's newline handling both
    measured zero change against the real sample chapters, each verified
    only against a locally reproduced guess at the real HTML shape (a
    newline inside one text run, then a newline between two <span> tags).
    Guessing a third shape risks the same outcome. This instead dumps the
    actual raw markup around each such occurrence directly, so the real
    structure is seen rather than inferred from log fragments.
    """
    samples = []
    seen = set()
    for match in EMBEDDED_STUB_PATTERN.finditer(text):
        number = match.group("number")
        if number in anchored_numbers or number in seen:
            continue
        seen.add(number)
        index = markup.find(number)
        if index == -1:
            continue
        start = max(0, index - 150)
        end = min(len(markup), index + 150)
        samples.append({"number": number, "rawMarkup": markup[start:end]})
        if len(samples) >= limit:
            break
    return samples


def is_subdivision_heading(line):
    """A centred heading dividing a chapter, carrying no section number."""
    if SECTION_NUMBER_ANYWHERE.search(line):
        return False
    if PAREN_HEADING_PATTERN.match(line):
        return True
    return bool(UPPER_HEADING_PATTERN.match(line)) and any(c.isalpha() for c in line)


def parse_chapter(markup, chapter_number):
    """Parse one chapter document into edition, chapter, subdivision and section rows."""
    text, bold_spans = normalize_chapter_text(markup)
    lines = list(line_spans(text))

    printed_number, chapter_name = parse_chapter_heading(lines, chapter_number)
    edition_year = parse_edition_year(lines)

    # A bold run is a section anchor when its text opens with a section number
    # followed by a catchline or a bracketed disposition stub.
    anchors = []
    for start, end in bold_spans:
        run = " ".join(text[start:end].split())
        if not run:
            continue
        catchline_match = SECTION_CATCHLINE_PATTERN.match(run)
        stub_match = SECTION_STUB_PATTERN.match(run)
        if stub_match is not None:
            anchors.append({
                "number": stub_match.group("number"),
                "catchline": None,
                "stub": stub_match.group("stub"),
                "start": start,
                "headingEnd": end,
            })
        elif catchline_match is not None:
            anchors.append({
                "number": catchline_match.group("number"),
                "catchline": catchline_match.group("catchline").strip() or None,
                "stub": None,
                "start": start,
                "headingEnd": end,
            })
        else:
            # A bold run that is just the bare number, with its bracket
            # printed in a following non-bold span -- see
            # BARE_NUMBER_PATTERN's comment for the real form this covers.
            bare_match = BARE_NUMBER_PATTERN.match(run)
            if bare_match is not None:
                # No length cap: a stub-only section's credit can run to
                # many citations (as long as any ordinary operative
                # section's own trailing credit already can), and a capped
                # window can miss the bracket's close entirely -- confirmed
                # against chapter 192's own real 192.500, whose citation
                # list runs past 400 characters before its final
                # disposition.
                following = FOLLOWING_STUB_PATTERN.match(text[end:])
                if following is not None:
                    anchors.append({
                        "number": bare_match.group("number"),
                        "catchline": None,
                        "stub": following.group("stub"),
                        "start": start,
                        "headingEnd": end + following.end(),
                    })

    anchors.sort(key=lambda item: item["start"])

    # A heading that divides no sections is not a subdivision of the body. The
    # contents list at the head of the chapter repeats the same headings above
    # unbolded entries, and the edition banner looks like one too; neither has
    # a section anchor beneath it before the next heading.
    candidates = [
        {"headingText": line, "start": start, "end": end}
        for line, start, end in lines
        if is_subdivision_heading(line)
    ]
    subdivisions = []
    for index, candidate in enumerate(candidates):
        limit = candidates[index + 1]["start"] if index + 1 < len(candidates) else len(text)
        if any(candidate["start"] < anchor["start"] < limit for anchor in anchors):
            subdivisions.append(candidate)

    sections = []
    problems = []
    foreign_anchors = []
    seen = set()
    for index, anchor in enumerate(anchors):
        next_anchor = anchors[index + 1]["start"] if index + 1 < len(anchors) else len(text)
        # A subdivision heading between this section and the next belongs to
        # neither: it ends this section's text rather than trailing it, which
        # is what let a heading swallow the section's own source credit.
        following_heading = next(
            (item["start"] for item in subdivisions if item["start"] > anchor["start"]),
            len(text),
        )
        end = min(next_anchor, following_heading)
        number = anchor["number"]
        if number in seen:
            problems.append(f"duplicate section number in chapter: {number}")
            continue
        seen.add(number)
        if chapter_number is not None and not number.startswith(f"{chapter_number}."):
            # A bolded citation to another chapter's section, not a heading
            # here. Recorded so the count stays visible, but it is not this
            # chapter's defect.
            foreign_anchors.append(number)
            continue

        # Editorial notes are split off first, from the section's raw
        # printed text, before either branch below ever sees it: every real
        # note comes after a section's own credit (stub or operative
        # alike), so splitting them off up front leaves the existing
        # credit/body handling untouched. See split_editorial_notes's
        # docstring for the block-boundary rule and FINDINGS.md for the
        # real forms that settled it.
        raw_span = text[anchor["headingEnd"]:end]
        pre_notes, raw_notes = split_editorial_notes(raw_span)
        notes = [
            {
                "text": note["text"],
                "charOffsetStart": anchor["headingEnd"] + note["charOffsetStart"],
                "charOffsetEnd": anchor["headingEnd"] + note["charOffsetEnd"],
            }
            for note in raw_notes
        ]

        # Both branches below only ever narrow pre_notes from its own left
        # edge inward (strip(), then a further left-anchored slice for a
        # trailing credit) -- body_char_offset_start is therefore exactly
        # anchor["headingEnd"] plus pre_notes's own leading whitespace,
        # regardless of which branch runs. This is what lets a cross-
        # reference match's position within body_text (see
        # ors_cross_references.py) be placed in the chapter's normalized
        # text without re-deriving it from body_text after the fact.
        body_char_offset_start = anchor["headingEnd"] + (
            len(pre_notes) - len(pre_notes.lstrip())
        )

        if anchor["stub"] is not None:
            status, renumbered_to = classify_stub(anchor["stub"])
            # A stub section has no operative text: the bracket is the whole
            # entry, and it is history rather than statute.
            credit = anchor["stub"]
            body = pre_notes.strip() or None
        else:
            status, renumbered_to = "operative", None
            body, credit = split_source_credit(pre_notes.strip())

        # The most recent heading above this section owns it.
        owning = None
        for subdivision in subdivisions:
            if subdivision["start"] < anchor["start"]:
                owning = subdivision
            else:
                break

        sections.append({
            "sectionNumber": number,
            "catchline": anchor["catchline"],
            "bodyText": body or None,
            "bodyTextCharOffsetStart": body_char_offset_start,
            "sourceCreditRaw": credit,
            "notes": notes,
            "status": status,
            "renumberedTo": renumbered_to,
            "subdivisionHeading": owning["headingText"] if owning else None,
            "charOffsetStart": anchor["start"],
            "charOffsetEnd": end,
        })

    return {
        "printedChapterNumber": printed_number,
        "chapterName": chapter_name,
        "editionYear": edition_year,
        "editionDiagnostics": None if edition_year else edition_diagnostics(lines),
        "headingDiagnostics": (
            None if chapter_name else heading_diagnostics(lines, chapter_number)
        ),
        "normalizedCharCount": len(text),
        "boldRunCount": len(bold_spans),
        "sections": sections,
        "subdivisions": subdivisions,
        "pendingChangeNotices": find_pending_change_notices(lines),
        "foreignAnchors": foreign_anchors,
        "unboldedStubLines": find_unbolded_stub_lines(
            lines, bold_spans, {anchor["number"] for anchor in anchors}
        ),
        "embeddedStubMarkupSamples": find_embedded_stub_markup_samples(
            markup, text, {anchor["number"] for anchor in anchors}
        ),
        "problems": problems,
    }


def build_rows(chapter_records, repo_root=None):
    """Turn parsed chapters into the relational rows defined in SCHEMA.md."""
    editions = {}
    chapters = []
    subdivisions = []
    sections = []
    source_credits = []
    section_notes = []
    pending_changes = []
    problems = []
    # "Formerly NNN.NNN", bare "Renumbered NNN.NNN" and "enacted in lieu of
    # NNN.NNN" segments name a section rather than citing a session law, so
    # they never become ors_source_credit rows. They are still real data, so
    # they are collected rather than dropped; SCHEMA.md has no table for
    # them yet, which is a deliberate scope limit recorded in ROADMAP.md.
    formerly_references = []
    renumber_references = []
    enacted_in_lieu_references = []
    # A credit segment that is neither a session-law citation nor one of the
    # two forms above. Surfaced explicitly rather than silently absorbed,
    # because it represents a real printed form this parser does not yet
    # understand.
    unparsed_credit_segments = []
    # Candidate section/range/chapter mentions found in body_text, resolved
    # into ors_cross_reference rows once every chapter has been walked (a
    # candidate can cite a section in a chapter parsed later in this same
    # call). See ors_cross_references.py's module docstring for the row
    # shape and why an unresolved citation keeps to_section_id null.
    cross_reference_candidates = []
    # sectionNumber -> sectionId, flat rather than scoped per edition: a
    # routine call always parses one edition's chapters (a whole-edition
    # rebuild for a new edition is its own separate call, not mixed into
    # this one), so a flat map is exact for every real call shape without
    # needing edition-aware plumbing resolve_cross_references would
    # otherwise have to carry through its own generic signature.
    section_ids_by_number = {}
    # Candidate editorial/preface note introductions ("Note:", "Notes:")
    # found in body_text. Increment 3's ors_section_note table has not been
    # extended to this form yet; this only measures where such blocks
    # appear, per find_editorial_note_candidates's own docstring.
    editorial_note_candidates = []

    for record in chapter_records:
        number = record["chapterNumber"]
        parsed = record["parsed"]
        edition_year = parsed["editionYear"]
        if edition_year is None:
            # editionId is the primary key of ors_edition and the
            # discriminator between editions in every other table, so a row
            # that cannot be filed against an edition is not emitted.
            problems.append(f"chapter {number} states no ORS edition year")
            continue
        edition_id = str(edition_year)
        editions.setdefault(edition_id, {
            "editionId": edition_id,
            "editionYear": edition_year,
            "chapterCount": 0,
        })
        editions[edition_id]["chapterCount"] += 1

        printed = parsed["printedChapterNumber"]
        if printed is not None and printed != number:
            problems.append(
                f"chapter {number} names itself {printed} in its own heading"
            )
            continue

        chapter_id = f"{edition_id}-{number}"
        chapters.append({
            "chapterId": chapter_id,
            "editionId": edition_id,
            "chapterNumber": number,
            "chapterSortKey": record["chapterSortKey"],
            "chapterName": parsed["chapterName"],
            "titleNumber": record.get("titleNumber"),
            "volumeNumber": record.get("volumeNumber"),
            "sourceUrl": record.get("sourceUrl"),
            "sourceSha256": record.get("sha256"),
            "sourceBytes": record.get("bytes"),
            "sourceEncoding": record.get("sourceEncoding"),
            "sectionCount": len(parsed["sections"]),
        })

        for ordinal, notice in enumerate(parsed["pendingChangeNotices"], start=1):
            pending_changes.append({
                "pendingChangeId": f"{chapter_id}-p{ordinal:03d}",
                "chapterId": chapter_id,
                "ordinal": ordinal,
                "sessionYear": notice["sessionYear"],
                "sessionLawChapter": notice["sessionLawChapter"],
                "changeKind": notice["changeKind"],
                "noticeText": notice["noticeText"],
                "charOffsetStart": notice["charOffsetStart"],
                "charOffsetEnd": notice["charOffsetEnd"],
            })

        subdivision_ids = {}
        for ordinal, subdivision in enumerate(parsed["subdivisions"], start=1):
            subdivision_id = f"{chapter_id}-sd{ordinal:04d}"
            subdivision_ids[subdivision["start"]] = subdivision_id
            subdivisions.append({
                "subdivisionId": subdivision_id,
                "chapterId": chapter_id,
                "headingText": subdivision["headingText"],
                "ordinal": ordinal,
                "charOffsetStart": subdivision["start"],
                "charOffsetEnd": subdivision["end"],
            })

        heading_to_id = {}
        for subdivision in parsed["subdivisions"]:
            heading_to_id.setdefault(
                subdivision["headingText"], subdivision_ids[subdivision["start"]]
            )

        for ordinal, section in enumerate(parsed["sections"], start=1):
            section_id = f"{edition_id}-{section['sectionNumber']}"
            section_ids_by_number[section["sectionNumber"]] = section_id
            sections.append({
                "sectionId": section_id,
                "chapterId": chapter_id,
                "subdivisionId": heading_to_id.get(section["subdivisionHeading"]),
                "sectionNumber": section["sectionNumber"],
                "sectionSortKey": section_sort_key(section["sectionNumber"]),
                "catchline": section["catchline"],
                "bodyText": section["bodyText"],
                "sourceCreditRaw": section["sourceCreditRaw"],
                "status": section["status"],
                "renumberedTo": section["renumberedTo"],
                "ordinal": ordinal,
                "charOffsetStart": section["charOffsetStart"],
                "charOffsetEnd": section["charOffsetEnd"],
            })

            if section["sourceCreditRaw"]:
                parsed_credit = parse_source_credit(section["sourceCreditRaw"])
                for credit_ordinal, citation in enumerate(parsed_credit["citations"], start=1):
                    source_credits.append({
                        "creditId": f"{section_id}-c{credit_ordinal:03d}",
                        "sectionId": section_id,
                        "ordinal": credit_ordinal,
                        "sessionYear": citation["sessionYear"],
                        "sessionLawChapter": citation["sessionLawChapter"],
                        "sessionLawSection": citation["sessionLawSection"],
                        "specialSession": citation["specialSession"],
                        "action": citation["action"],
                        "rawCredit": citation["rawSegment"],
                    })
                formerly_references.extend(
                    {"sectionId": section_id, "sectionNumber": number}
                    for number in parsed_credit["formerlyReferences"]
                )
                renumber_references.extend(
                    {"sectionId": section_id, "sectionNumber": number}
                    for number in parsed_credit["renumberReferences"]
                )
                enacted_in_lieu_references.extend(
                    {"sectionId": section_id, "sectionNumber": number}
                    for number in parsed_credit["enactedInLieuReferences"]
                )
                if parsed_credit["unparsedSegments"]:
                    unparsed_credit_segments.append({
                        "sectionId": section_id,
                        "segments": parsed_credit["unparsedSegments"],
                    })

            for note_ordinal, note in enumerate(section["notes"], start=1):
                section_notes.append({
                    "noteId": f"{section_id}-n{note_ordinal:03d}",
                    "sectionId": section_id,
                    "noteKind": "editorial_note",
                    "noteText": note["text"],
                    "ordinal": note_ordinal,
                    "charOffsetStart": note["charOffsetStart"],
                    "charOffsetEnd": note["charOffsetEnd"],
                })

            if section["bodyText"]:
                base = section["bodyTextCharOffsetStart"]
                cross_reference_candidates.extend(
                    {
                        "sectionId": section_id,
                        **candidate,
                        # Absolute, into the chapter's own normalized text --
                        # see body_char_offset_start's own comment in
                        # parse_chapter for why body_text's own offsets
                        # translate directly with no further adjustment.
                        "charOffsetStart": base + candidate["charOffsetStart"],
                        "charOffsetEnd": base + candidate["charOffsetEnd"],
                    }
                    for candidate in find_cross_reference_candidates(section["bodyText"])
                )
                # Confirms extraction rather than motivating it now: every
                # real note this measured should already be a row in
                # section_notes above, so a survivor here means a note form
                # split_editorial_notes does not yet recognize.
                editorial_note_candidates.extend(
                    {"sectionId": section_id, **candidate}
                    for candidate in find_editorial_note_candidates(section["bodyText"])
                )

        problems.extend(f"chapter {number}: {item}" for item in parsed["problems"])

    cross_references = resolve_cross_references(cross_reference_candidates, section_ids_by_number)

    return {
        "editions": sorted(editions.values(), key=lambda item: item["editionId"]),
        "chapters": chapters,
        "subdivisions": subdivisions,
        "sections": sections,
        "sourceCredits": source_credits,
        "sectionNotes": section_notes,
        "pendingChanges": pending_changes,
        "formerlyReferences": formerly_references,
        "renumberReferences": renumber_references,
        "enactedInLieuReferences": enacted_in_lieu_references,
        "unparsedCreditSegments": unparsed_credit_segments,
        "crossReferences": cross_references,
        "crossReferenceCandidates": cross_reference_candidates,
        "editorialNoteCandidates": editorial_note_candidates,
        "problems": problems,
    }


def section_sort_key(section_number):
    """Order sections the way the statute book does, fraction included."""
    chapter_part, _, fraction = section_number.partition(".")
    return f"{chapter_sort_key(chapter_part)}.{fraction}"


def check_referential_integrity(rows):
    """The SCHEMA.md invariants, as a list of violations."""
    violations = []
    edition_ids = {item["editionId"] for item in rows["editions"]}
    chapter_ids = {item["chapterId"] for item in rows["chapters"]}
    subdivision_ids = {item["subdivisionId"] for item in rows["subdivisions"]}

    for chapter in rows["chapters"]:
        if chapter["editionId"] not in edition_ids:
            violations.append(f"chapter {chapter['chapterId']} has no edition")
        if not chapter["sourceSha256"]:
            violations.append(f"chapter {chapter['chapterId']} has no pinned digest")

    for subdivision in rows["subdivisions"]:
        if subdivision["chapterId"] not in chapter_ids:
            violations.append(f"subdivision {subdivision['subdivisionId']} has no chapter")

    seen_sections = set()
    for section in rows["sections"]:
        if section["chapterId"] not in chapter_ids:
            violations.append(f"section {section['sectionId']} has no chapter")
        if section["subdivisionId"] and section["subdivisionId"] not in subdivision_ids:
            violations.append(f"section {section['sectionId']} has a dangling subdivision")
        if section["sectionId"] in seen_sections:
            violations.append(f"duplicate section id {section['sectionId']}")
        seen_sections.add(section["sectionId"])
        chapter_number = section["chapterId"].split("-", 1)[1]
        if not section["sectionNumber"].startswith(f"{chapter_number}."):
            violations.append(
                f"section {section['sectionId']} is filed under chapter {chapter_number}"
            )
        if section["status"] not in SECTION_STATUSES:
            violations.append(
                f"section {section['sectionId']} has unknown status {section['status']}"
            )
        if section["charOffsetStart"] >= section["charOffsetEnd"]:
            violations.append(f"section {section['sectionId']} has an empty span")

    for chapter in rows["chapters"]:
        if chapter["sectionCount"] == 0:
            violations.append(f"chapter {chapter['chapterId']} produced no sections")

    seen_credits = set()
    for credit in rows["sourceCredits"]:
        if credit["sectionId"] not in seen_sections:
            violations.append(f"credit {credit['creditId']} has no section")
        if credit["creditId"] in seen_credits:
            violations.append(f"duplicate credit id {credit['creditId']}")
        seen_credits.add(credit["creditId"])
        if credit["action"] not in CREDIT_ACTIONS:
            violations.append(
                f"credit {credit['creditId']} has unknown action {credit['action']}"
            )
        if not 1850 <= credit["sessionYear"] <= 2100:
            violations.append(
                f"credit {credit['creditId']} has an implausible session year {credit['sessionYear']}"
            )

    seen_pending_changes = set()
    for pending_change in rows["pendingChanges"]:
        if pending_change["chapterId"] not in chapter_ids:
            violations.append(
                f"pending change {pending_change['pendingChangeId']} has no chapter"
            )
        if pending_change["pendingChangeId"] in seen_pending_changes:
            violations.append(f"duplicate pending change id {pending_change['pendingChangeId']}")
        seen_pending_changes.add(pending_change["pendingChangeId"])
        if pending_change["changeKind"] not in PENDING_CHANGE_KINDS:
            violations.append(
                f"pending change {pending_change['pendingChangeId']} has unknown kind "
                f"{pending_change['changeKind']}"
            )
        if not 1850 <= pending_change["sessionYear"] <= 2100:
            violations.append(
                f"pending change {pending_change['pendingChangeId']} has an implausible "
                f"session year {pending_change['sessionYear']}"
            )

    seen_notes = set()
    for note in rows["sectionNotes"]:
        if note["sectionId"] not in seen_sections:
            violations.append(f"note {note['noteId']} has no section")
        if note["noteId"] in seen_notes:
            violations.append(f"duplicate note id {note['noteId']}")
        seen_notes.add(note["noteId"])
        if note["noteKind"] not in NOTE_KINDS:
            violations.append(f"note {note['noteId']} has unknown kind {note['noteKind']}")
        if not note["noteText"]:
            violations.append(f"note {note['noteId']} has no text")
        if note["charOffsetStart"] >= note["charOffsetEnd"]:
            violations.append(f"note {note['noteId']} has an empty span")

    seen_references = set()
    for reference in rows["crossReferences"]:
        if reference["fromSectionId"] not in seen_sections:
            violations.append(f"cross reference {reference['referenceId']} has no from-section")
        if reference["referenceId"] in seen_references:
            violations.append(f"duplicate cross reference id {reference['referenceId']}")
        seen_references.add(reference["referenceId"])
        if reference["referenceKind"] not in REFERENCE_KINDS:
            violations.append(
                f"cross reference {reference['referenceId']} has unknown kind "
                f"{reference['referenceKind']}"
            )
        # to_section_id is allowed to be null -- an unresolved citation is
        # real data per SCHEMA.md, not a violation.
        if reference["charOffsetStart"] >= reference["charOffsetEnd"]:
            violations.append(f"cross reference {reference['referenceId']} has an empty span")

    return violations


SECTION_STATUSES = {"operative", "repealed", "renumbered", "reserved", "note_only"}
CREDIT_ACTIONS = {"enacted", "amended", "renumbered", "repealed", "unspecified"}
NOTE_KINDS = {"source_credit", "editorial_note", "preface_note"}
REFERENCE_KINDS = {"section", "range_start", "range_end", "chapter"}
PENDING_CHANGE_KINDS = {
    "amended_or_repealed_elsewhere", "new_series_section", "new_compiled_section",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--rows", help="where to write the emitted relational rows")
    parser.add_argument("--limit", type=int, help="parse at most this many chapters")
    args = parser.parse_args(argv)

    acquisition = json.loads(Path(args.acquisition_report).read_text())
    acquired = [
        chapter for chapter in acquisition.get("chapters", [])
        if chapter.get("ok") and chapter.get("sourceFormat") == "html"
    ]
    if args.limit is not None:
        acquired = acquired[: args.limit]

    records = []
    unreadable = []
    for chapter in acquired:
        path = Path(chapter["fixture"])
        if not path.exists():
            unreadable.append({"chapterNumber": chapter["chapterNumber"], "error": "fixture missing"})
            continue
        data = path.read_bytes()
        markup, encoding = decode_markup(data, declared_charset(data))
        parsed = parse_chapter(markup, chapter["chapterNumber"])
        record = dict(chapter)
        record["sourceEncoding"] = encoding
        record["parsed"] = parsed
        record["chapterSortKey"] = chapter.get("chapterSortKey") or chapter_sort_key(
            chapter["chapterNumber"]
        )
        records.append(record)

    rows = build_rows(records)
    violations = check_referential_integrity(rows)
    foreign = [
        {"chapterNumber": record["chapterNumber"], "anchors": record["parsed"]["foreignAnchors"]}
        for record in records
        if record["parsed"]["foreignAnchors"]
    ]
    unbolded_stubs = [
        {"chapterNumber": record["chapterNumber"], **item}
        for record in records
        for item in record["parsed"]["unboldedStubLines"]
    ]
    embedded_stub_markup_samples = [
        {"chapterNumber": record["chapterNumber"], **item}
        for record in records
        for item in record["parsed"]["embeddedStubMarkupSamples"]
    ]

    report = {
        "schemaVersion": 1,
        "stage": "parse",
        "parsedChapterCount": len(records),
        "unreadableChapterCount": len(unreadable),
        "editionCount": len(rows["editions"]),
        "chapterRowCount": len(rows["chapters"]),
        "subdivisionRowCount": len(rows["subdivisions"]),
        "sectionRowCount": len(rows["sections"]),
        "statusCounts": status_counts(rows["sections"]),
        "sourceCreditRowCount": len(rows["sourceCredits"]),
        "sectionNoteRowCount": len(rows["sectionNotes"]),
        "pendingChangeRowCount": len(rows["pendingChanges"]),
        "pendingChangeCountByKind": pending_change_counts_by_kind(rows["pendingChanges"]),
        "formerlyReferenceCount": len(rows["formerlyReferences"]),
        "renumberReferenceCount": len(rows["renumberReferences"]),
        "enactedInLieuReferenceCount": len(rows["enactedInLieuReferences"]),
        # A credit segment that is neither a session-law citation nor a
        # recognized non-citation form (Formerly/Renumbered). Gated at zero:
        # every real form recorded in FINDINGS.md parses cleanly, so a
        # non-zero count here is a printed form this parser does not yet
        # understand, not routine noise.
        "unparsedCreditSegmentCount": sum(
            len(item["segments"]) for item in rows["unparsedCreditSegments"]
        ),
        # Uncapped except for a generous ceiling: a narrow cap here cost a
        # full CI round trip once already, revealing only 10 of 103 real
        # unparsed segments and leaving the rest to a second discovery round.
        "unparsedCreditSegments": rows["unparsedCreditSegments"][:500],
        # Bold runs naming another chapter's section: bolded citations, not
        # headings here. Counted so the rule stays observable, but not a
        # failure, since they are not this chapter's rows.
        "foreignAnchorCount": sum(len(item["anchors"]) for item in foreign),
        "foreignAnchors": foreign,
        # A stub-shaped line ("number [Repealed by ...]") that bold-run
        # anchoring does not reach, so it produced no section row at all.
        # Diagnostic only for now, not gated: the true scale of this gap is
        # not yet known (see find_unbolded_stub_lines's docstring for why the
        # 138-in-646A figure FINDINGS.md first recorded overstates it), so
        # this is measured before a fix is written rather than guessed at.
        "unboldedStubLineCount": len(unbolded_stubs),
        "unboldedStubDistinctNumberCount": len({item["number"] for item in unbolded_stubs}),
        "unboldedStubLines": unbolded_stubs[:500],
        # Raw markup ground truth: two guesses at the real HTML shape around
        # an embedded stub both measured zero change on real data. See
        # find_embedded_stub_markup_samples's docstring. Diagnostic only.
        "embeddedStubMarkupSamples": embedded_stub_markup_samples[:50],
        # Candidate section/range/chapter mentions found in body_text,
        # measured the same deliberately generous and unopinionated way
        # since before resolution was built. See ors_cross_references.py's
        # docstring. Diagnostic only, not gated: resolution rate depends on
        # which chapters the fixed sample happens to include, not on
        # extraction correctness, so it is not a pass/fail signal the way
        # unparsedCreditSegmentCount or editorialNoteCandidateCount are.
        "crossReferenceCandidateCount": len(rows["crossReferenceCandidates"]),
        "crossReferenceCandidatesByKind": candidate_counts_by_kind(
            rows["crossReferenceCandidates"]
        ),
        "crossReferenceCandidates": rows["crossReferenceCandidates"][:500],
        "crossReferenceRowCount": len(rows["crossReferences"]),
        "crossReferenceResolvedCount": sum(
            1 for item in rows["crossReferences"] if item["toSectionId"] is not None
        ),
        "crossReferences": rows["crossReferences"][:500],
        "sectionNotes": rows["sectionNotes"][:500],
        # A survivor here after extraction means a "Note:"/"Notes:" form
        # split_editorial_notes does not yet recognize -- every real note
        # this pass found before extraction was built is now a row in
        # sectionNotes above. Kept as a diagnostic (not yet gated) until a
        # real CI run confirms this actually reads zero, the same
        # measure-then-gate order every earlier field in this pipeline
        # followed.
        "editorialNoteCandidateCount": len(rows["editorialNoteCandidates"]),
        "editorialNoteCandidates": rows["editorialNoteCandidates"][:500],
        "chaptersWithoutName": [
            chapter["chapterNumber"] for chapter in rows["chapters"] if not chapter["chapterName"]
        ],
        "headingDiagnostics": [
            {
                "chapterNumber": record["chapterNumber"],
                **record["parsed"]["headingDiagnostics"],
            }
            for record in records
            if record["parsed"]["headingDiagnostics"] is not None
        ][:3],
        "editionDiagnostics": [
            {
                "chapterNumber": record["chapterNumber"],
                **record["parsed"]["editionDiagnostics"],
            }
            for record in records
            if record["parsed"]["editionDiagnostics"] is not None
        ][:3],
        "problems": rows["problems"],
        "integrityViolations": violations,
        "unreadable": unreadable,
        "valid": (
            bool(rows["sections"])
            and not rows["problems"]
            and not violations
            and not unreadable
            and all(chapter["chapterName"] for chapter in rows["chapters"])
            and not rows["unparsedCreditSegments"]
            # Confirmed against real CI data (see FINDINGS.md): every real
            # note form the measurement pass ever found is now a row in
            # sectionNotes, so a survivor here is a real gap, not noise.
            and not rows["editorialNoteCandidates"]
        ),
        "perChapter": [
            {
                "chapterNumber": chapter["chapterNumber"],
                "chapterName": chapter["chapterName"],
                "titleNumber": chapter["titleNumber"],
                "sectionCount": chapter["sectionCount"],
            }
            for chapter in rows["chapters"]
        ],
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    if args.rows:
        Path(args.rows).write_text(json.dumps(rows, indent=2) + "\n")

    print(json.dumps({
        "valid": report["valid"],
        "parsedChapterCount": report["parsedChapterCount"],
        "editionCount": report["editionCount"],
        "sectionRowCount": report["sectionRowCount"],
        "subdivisionRowCount": report["subdivisionRowCount"],
        "statusCounts": report["statusCounts"],
        "foreignAnchorCount": report["foreignAnchorCount"],
        "sourceCreditRowCount": report["sourceCreditRowCount"],
        "sectionNoteRowCount": report["sectionNoteRowCount"],
        "pendingChangeRowCount": report["pendingChangeRowCount"],
        "pendingChangeCountByKind": report["pendingChangeCountByKind"],
        "unparsedCreditSegmentCount": report["unparsedCreditSegmentCount"],
        "unboldedStubLineCount": report["unboldedStubLineCount"],
        "unboldedStubDistinctNumberCount": report["unboldedStubDistinctNumberCount"],
        "crossReferenceCandidateCount": report["crossReferenceCandidateCount"],
        "crossReferenceCandidatesByKind": report["crossReferenceCandidatesByKind"],
        "crossReferenceRowCount": report["crossReferenceRowCount"],
        "crossReferenceResolvedCount": report["crossReferenceResolvedCount"],
        "editorialNoteCandidateCount": report["editorialNoteCandidateCount"],
        "problemCount": len(report["problems"]),
        "chaptersWithoutName": report["chaptersWithoutName"],
        "integrityViolationCount": len(violations),
    }, indent=2))
    return 0 if report["valid"] else 1


def status_counts(sections):
    counts = {}
    for section in sections:
        counts[section["status"]] = counts.get(section["status"], 0) + 1
    return dict(sorted(counts.items()))


def candidate_counts_by_kind(candidates):
    counts = {}
    for candidate in candidates:
        counts[candidate["kind"]] = counts.get(candidate["kind"], 0) + 1
    return dict(sorted(counts.items()))


def pending_change_counts_by_kind(pending_changes):
    counts = {}
    for pending_change in pending_changes:
        counts[pending_change["changeKind"]] = counts.get(pending_change["changeKind"], 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    sys.exit(main())
