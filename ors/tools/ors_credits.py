#!/usr/bin/env python3
"""Parse bracketed ORS source-credit legislative history into rows.

Increment 2 already separates a section's trailing bracketed history from its
statutory text and keeps it as `sourceCreditRaw`. This module parses that
string into the `ors_source_credit` rows SCHEMA.md defines.

Every form here is drawn from real credit strings, first from FINDINGS.md and
then from the unparsed-segment diagnostic's first two real runs against the
sample chapters:

    [1971 c.743 s1]
    [1971 c.743 s3; 1973 c.836 s339; 2025 c.161 s4]
    [Repealed by 1973 c.794 s34]
    [Amended by 1961 c.160 s4; repealed by 1973 c.794 s34]
    [Formerly 646.185; repealed by 2009 c.170 s4]
    [1981 s.s. c.1 s3; 1995 c.658 s7; 1995 c.781 s3; 2013 c.155 s2]
    [2002 s.s.1 c.10 s7]                          -- numbered special session
    [2013 c.154 ss2,3]                            -- plural section, comma list
    [2001 c.823 s25 (enacted in lieu of 8.172)]   -- trailing parenthetical
    [reenacted by 1997 c.196 s3]                  -- a fourth action keyword
    [renumbered 1.179 in 2025]                    -- renumber note carrying a year
    [2009 c.431 s6 and 2009 c.816 s15]            -- two citations joined by "and"
    [Derived from 1983 c.740 s1]                  -- a fifth action keyword, uses "from"
    [subsection (3) enacted as 1961 c.150 s5]     -- citation scoped to one subsection
    [Formerly subsections (1) to (3) of 192.450]  -- Formerly with a subsection range
    [1977 c.517 s8(2),(3)]                        -- one section, two of its subsections
    [repealed by 2001 c.596 s25 (90.771 enacted in lieu of 90.770)]
                                                   -- trailing parenthetical whose own
                                                   -- first token is a section number

A citation with no leading action word states no action, and SCHEMA.md is
explicit that action must not be guessed for it: it is recorded as
`unspecified` rather than inferred as an enactment or amendment. A segment
that is not a session-law citation and not a recognized non-citation form
(`Formerly ...`, bare `Renumbered ...`) is reported rather than dropped,
because a form this parser does not yet understand is real data until proven
otherwise.

Subsection scoping ("subsection (3) enacted as ...", the "(2),(3)" suffix in
"s8(2),(3)") is read past to reach the citation underneath, but which
subsection is not itself modeled: SCHEMA.md's source-credit table is scoped
to whole ORS sections, and a subsection-level table is future work, recorded
in ROADMAP.md rather than silently implied by dropping the detail here.
"""
import re

# Prefixes stripped ahead of a citation, in the order they are tried. Each
# maps to the SCHEMA.md action it states:
#   - "Amended/Repealed/Renumbered/Reenacted by" -- ordinary keyword citations.
#     "Reenacted" has no matching SCHEMA.md value, so it maps to "enacted":
#     the keyword states this session law (re-)established the section.
#   - "Derived from" -- states origin without saying "by"; likewise "enacted".
#   - "subsection(s) (N)[ to (M)] enacted as" -- the citation applies to only
#     part of the section. The scoping is not modeled (see module docstring),
#     but the citation underneath still is, as an enactment.
CREDIT_PREFIX_PATTERNS = [
    (re.compile(r"^(?P<action>Amended|Repealed|Renumbered|Reenacted)\s+by\s+", re.IGNORECASE),
     {"amended": "amended", "repealed": "repealed", "renumbered": "renumbered", "reenacted": "enacted"}),
    (re.compile(r"^Derived\s+from\s+", re.IGNORECASE), "enacted"),
    (re.compile(
        r"^subsections?\s*\([^)]*\)(?:\s+to\s*\([^)]*\))?\s+enacted\s+as\s+", re.IGNORECASE
    ), "enacted"),
]
# A session-law citation: year, optional special-session marker, chapter,
# section(s), optional trailing parenthetical annotation.
#
# The special-session marker is either bare ("s.s.", pre-2000s convention) or
# numbered with no space before the digit ("s.s.1", "s.s.3"); both are
# followed by a space before "c.".
#
# The section mark is printed as the section sign, singular (S) or doubled
# for a plural citation (SS); a bare "s." form is also accepted since not
# every source is confirmed to use the sign. A doubled mark introduces a
# comma-separated list ("SS2,3", "SS7,7a"): more than one section. A
# subsection suffix ("S8(2),(3)") is a single section with more than one
# subsection, not more than one section, so a list item with no leading
# digit ("(3)") is a continuation of the previous item's section number
# rather than a section of its own.
#
# A trailing "(...)" is a parenthetical annotation -- "(enacted in lieu of
# 8.172)", "(90.771 enacted in lieu of 90.770)" -- kept in the raw segment
# but not otherwise modeled. It is never mistaken for a subsection-list
# continuation ("(2)", "(3)") because that quantified group above is greedy
# and already consumes every such continuation as part of `sections`; a
# parenthetical reaching this point necessarily failed that narrower shape
# (it holds a dotted section number, words, or both), whatever digit it
# starts with.
CREDIT_CITATION_PATTERN = re.compile(
    r"^(?P<year>(?:18|19|20)\d{2})\s*"
    r"(?P<special>s\.\s*s\.\s*\d*)?\s*"
    r"c\.\s*(?P<chapter>\d+)"
    r"(?:\s*(?:§§|§|s\.)\s*"
    r"(?P<sections>(?:[0-9]+[a-z]?)?(?:\s*\([0-9]+[a-z]?\))*"
    r"(?:\s*,\s*(?:[0-9]+[a-z]?)?(?:\s*\([0-9]+[a-z]?\))*)*))?"
    r"(?:\s*\([^)]*\))?\s*$",
    re.IGNORECASE,
)
SPECIAL_SESSION_NUMBER_PATTERN = re.compile(r"(\d+)")
SECTION_LIST_ITEM_PATTERN = re.compile(r"^([0-9]+[a-z]?)")
# "Formerly 646.185" -- this section used to be numbered 646.185. An optional
# "subsections (1) to (3) of " qualifier narrows which part of the destination
# section, as in "Formerly subsections (1) to (3) of 192.450"; the qualifier
# is read past rather than modeled, same as the "enacted as" prefixes above.
# Neither form is a session-law citation, so neither becomes a credit row.
FORMERLY_REFERENCE_PATTERN = re.compile(
    r"^Formerly\s+(?:subsections?\s*\([^)]*\)(?:\s+to\s*\([^)]*\))?\s+of\s+)?"
    r"(?P<number>\d{1,3}[A-Z]?\.\d{3})$",
    re.IGNORECASE,
)
# "Renumbered 161.045" with no "by" and no session citation: a bare
# destination reference, not a session-law citation either. An optional
# trailing "in YYYY" is a note on when the renumbering happened, not part of
# the destination, and is discarded rather than parsed into a session year:
# it is not stated to be the session that did the renumbering.
BARE_RENUMBER_PATTERN = re.compile(
    r"^Renumbered\s+(?P<number>\d{1,3}[A-Z]?\.\d{3})"
    r"(?:\s+in\s+(?:18|19|20)\d{2})?$",
    re.IGNORECASE,
)
# Two full citations joined by "and" instead of a semicolon: "2009 c.431 §6
# and 2009 c.816 §15". Tried only after a segment fails to parse as one
# citation outright, so it never fires on ordinary text that merely contains
# the word "and".
AND_JOIN_PATTERN = re.compile(r"\s+and\s+", re.IGNORECASE)


def strip_brackets(raw_credit):
    body = raw_credit.strip()
    if body.startswith("[") and body.endswith("]"):
        body = body[1:-1]
    return body


def split_credit_segments(body):
    """Split a credit body on top-level semicolons.

    No citation form observed contains an embedded semicolon, so a plain
    split is sufficient; a citation is not nested inside another.
    """
    return [segment.strip() for segment in body.split(";") if segment.strip()]


def _special_session_number(special_text):
    """Return the special-session ordinal from a matched marker, or 1.

    "s.s." with no digit is the pre-2000s bare form and is recorded as 1,
    since the marker states a special session without naming one. "s.s.3"
    states the third special session explicitly.
    """
    if not special_text:
        return None
    digits = SPECIAL_SESSION_NUMBER_PATTERN.search(special_text)
    return int(digits.group(1)) if digits else 1


def _section_numbers(sections_text):
    """Expand a citation's section-list text into individual section numbers.

    "2,3" is two sections. "8(2),(3)" is one section (8) with a subsection
    suffix on each list item; an item with no leading digit continues the
    previous item's section rather than naming a section of its own, so it
    contributes no further number. Returns [None] when there was no section
    list at all.
    """
    if not sections_text:
        return [None]
    numbers = []
    for item in sections_text.split(","):
        match = SECTION_LIST_ITEM_PATTERN.match(item.strip())
        if match is not None:
            numbers.append(match.group(1))
    return numbers or [None]


def _parse_citation_segment(segment):
    """Parse one segment as a single action-qualified citation.

    Returns a list of citation dicts (more than one for a multi-section
    list), or None if the segment is not a citation at all.
    """
    action = None
    remainder = segment
    for pattern, action_value in CREDIT_PREFIX_PATTERNS:
        match = pattern.match(segment)
        if match is None:
            continue
        action = action_value[match.group("action").lower()] if isinstance(action_value, dict) else action_value
        remainder = segment[match.end():]
        break

    citation_match = CREDIT_CITATION_PATTERN.match(remainder.strip())
    if citation_match is None:
        return None

    return [
        {
            "action": action or "unspecified",
            "sessionYear": int(citation_match.group("year")),
            "specialSession": _special_session_number(citation_match.group("special")),
            "sessionLawChapter": int(citation_match.group("chapter")),
            "sessionLawSection": section_number,
            "rawSegment": segment,
        }
        for section_number in _section_numbers(citation_match.group("sections"))
    ]


def parse_source_credit(raw_credit):
    """Parse one bracketed credit string into its component references.

    Returns a dict:
      citations: [{action, sessionYear, specialSession, sessionLawChapter,
                   sessionLawSection, rawSegment}], in printed order
      formerlyReferences: [section_number, ...]
      renumberReferences: [section_number, ...]
      unparsedSegments: [segment, ...]

    A citation naming several sections under one doubled section mark
    ("§§2,3") becomes one row per section number, all sharing the same
    year/chapter/action and the segment's full original text, so each row
    still joins to exactly one amendment-parser section.
    """
    segments = split_credit_segments(strip_brackets(raw_credit))
    citations = []
    formerly = []
    renumbers = []
    unparsed = []

    for segment in segments:
        formerly_match = FORMERLY_REFERENCE_PATTERN.match(segment)
        if formerly_match is not None:
            formerly.append(formerly_match.group("number"))
            continue

        renumber_match = BARE_RENUMBER_PATTERN.match(segment)
        if renumber_match is not None:
            renumbers.append(renumber_match.group("number"))
            continue

        parsed = _parse_citation_segment(segment)
        if parsed is not None:
            citations.extend(parsed)
            continue

        and_parts = AND_JOIN_PATTERN.split(segment)
        if len(and_parts) == 2:
            parsed_parts = [_parse_citation_segment(part) for part in and_parts]
            if all(part is not None for part in parsed_parts):
                for part in parsed_parts:
                    citations.extend(part)
                continue

        unparsed.append(segment)

    return {
        "citations": citations,
        "formerlyReferences": formerly,
        "renumberReferences": renumbers,
        "unparsedSegments": unparsed,
    }
