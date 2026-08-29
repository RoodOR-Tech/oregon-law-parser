#!/usr/bin/env python3
"""Parse bracketed ORS source-credit legislative history into rows.

Increment 2 already separates a section's trailing bracketed history from its
statutory text and keeps it as `sourceCreditRaw`. This module parses that
string into the `ors_source_credit` rows SCHEMA.md defines.

Every form here is drawn from real credit strings recorded in FINDINGS.md:

    [1971 c.743 s1]
    [1971 c.743 s3; 1973 c.836 s339; 2025 c.161 s4]
    [Repealed by 1973 c.794 s34]
    [Amended by 1961 c.160 s4; repealed by 1973 c.794 s34]
    [Formerly 646.185; repealed by 2009 c.170 s4]
    [1981 s.s. c.1 s3; 1995 c.658 s7; 1995 c.781 s3; 2013 c.155 s2]

A citation with no leading action word states no action, and SCHEMA.md is
explicit that action must not be guessed for it: it is recorded as
`unspecified` rather than inferred as an enactment or amendment. A segment
that is not a session-law citation and not a recognized non-citation form
(`Formerly ...`, bare `Renumbered ...`) is reported rather than dropped,
because a form this parser does not yet understand is real data until proven
otherwise.
"""
import re

# "Amended by", "Repealed by" or "Renumbered by" ahead of a citation. Only a
# citation carries the "by": bare "Formerly X" and "Renumbered X" are handled
# separately because they name a section, not a session law.
CREDIT_ACTION_PATTERN = re.compile(
    r"^(?P<action>Amended|Repealed|Renumbered)\s+by\s+", re.IGNORECASE
)
# A session-law citation: year, optional special-session marker, chapter,
# optional section. The section mark is printed as section-sign; a bare "s."
# form is also accepted since not every source is confirmed to use the sign.
CREDIT_CITATION_PATTERN = re.compile(
    r"^(?P<year>(?:18|19|20)\d{2})\s*(?P<special>s\.\s*s\.)?\s*c\.\s*(?P<chapter>\d+)"
    r"(?:\s*(?:§|s\.)\s*(?P<section>[0-9]+[a-z]?))?$",
    re.IGNORECASE,
)
# "Formerly 646.185" -- this section used to be numbered 646.185. Not a
# session-law citation, so it never becomes an ors_source_credit row.
FORMERLY_REFERENCE_PATTERN = re.compile(
    r"^Formerly\s+(?P<number>\d{1,3}[A-Z]?\.\d{3})$", re.IGNORECASE
)
# "Renumbered 161.045" with no "by" and no session citation: a bare
# destination reference, not a session-law citation either.
BARE_RENUMBER_PATTERN = re.compile(
    r"^Renumbered\s+(?P<number>\d{1,3}[A-Z]?\.\d{3})$", re.IGNORECASE
)


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


def parse_source_credit(raw_credit):
    """Parse one bracketed credit string into its component references.

    Returns a dict:
      citations: [{action, sessionYear, specialSession, sessionLawChapter,
                   sessionLawSection, rawSegment}], in printed order
      formerlyReferences: [section_number, ...]
      renumberReferences: [section_number, ...]
      unparsedSegments: [segment, ...]
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

        action = None
        remainder = segment
        action_match = CREDIT_ACTION_PATTERN.match(segment)
        if action_match is not None:
            action = action_match.group("action").lower()
            remainder = segment[action_match.end():]

        citation_match = CREDIT_CITATION_PATTERN.match(remainder.strip())
        if citation_match is None:
            unparsed.append(segment)
            continue

        citations.append({
            "action": action or "unspecified",
            "sessionYear": int(citation_match.group("year")),
            "specialSession": 1 if citation_match.group("special") else None,
            "sessionLawChapter": int(citation_match.group("chapter")),
            "sessionLawSection": citation_match.group("section"),
            "rawSegment": segment,
        })

    return {
        "citations": citations,
        "formerlyReferences": formerly,
        "renumberReferences": renumbers,
        "unparsedSegments": unparsed,
    }
