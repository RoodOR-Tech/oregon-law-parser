#!/usr/bin/env python3
"""Measure section-to-section citations printed in ORS statutory text.

Increment 4's `ors_cross_reference` table has not been built yet. Before
writing extraction and resolution rules, this module only measures what
citation shapes actually appear in `body_text` across the real sample
chapters -- the same discipline every earlier table in this pipeline
followed (the structure probe before the chapter parser, the unparsed-
segment diagnostic before the credit-parsing rule, the stub-line diagnostic
before an anchoring rule). What CI reports from this pass decides what
`ors_cross_reference` rows extraction actually needs to handle.

Real fragments already seen in an earlier structure-probe sample for
chapter 1 (via `sampleAmbiguousSectionLines`) motivate the shapes tried
here:

    1.194 to 1.200
    174.120 and other rules and laws that refer to periods of time...
    153.770, including use of electronic citations for parking...

None of those fragments is complete enough to know the surrounding phrasing
(is "ORS" printed before the number every time? is a chapter ever cited
without a section?), so this pass is deliberately generous and
unopinionated: it finds candidate section-number, range and chapter
mentions and reports each with surrounding context, rather than guessing the
phrasing now. `reference_kind` and resolution against `to_section_id` are
written once real samples from CI show what forms exist.

A real CI run already settled one of those open questions the hard way:
a bare "chapter NNN" is not always an ORS chapter. Real printed forms
include both

    issued under ORS 271.390 or ORS chapter 287A to finance capital costs
    Note: Sections 3 and 4, chapter 88, Oregon Laws 2025, provide:
    the amount specified in section 1 (6), chapter 705, Oregon Laws 2013

and only the first is a genuine ORS chapter cross-reference -- it is
preceded by "ORS". The other two cite a session-law chapter ("chapter 88,
Oregon Laws 2025"), the same numbering `ors_source_credit` already uses for
`session_law_chapter`; conflating the two would resolve a `chapter`
candidate against the wrong table entirely. Every real ORS chapter mention
observed is immediately preceded by "ORS ", so `CHAPTER_MENTION_PATTERN`
requires that prefix rather than trying to rule out "Oregon Laws" or a
preceding "section N," after the fact -- a session-law chapter mention
simply does not match this pattern at all, rather than being caught and
then rejected.
"""
import re

SECTION_NUMBER_PATTERN = re.compile(r"\d{1,3}[A-Z]?\.\d{3}")
# "161.005 to 161.055" -- a range. Both endpoints are reported once as a
# single "range" candidate, not also as two separate "section" candidates.
RANGE_PATTERN = re.compile(
    r"(?P<start>\d{1,3}[A-Z]?\.\d{3})\s+to\s+(?P<end>\d{1,3}[A-Z]?\.\d{3})"
)
# Requires the "ORS" prefix (as a lookbehind, so the match itself is still
# just the "chapter NNN" phrase): see the module docstring for the real
# session-law chapter mentions ("chapter 88, Oregon Laws 2025") this
# excludes by construction rather than by rejecting them after a match.
CHAPTER_MENTION_PATTERN = re.compile(
    r"(?<=\bORS)\s+chapter\s+(?P<number>\d{1,3}[A-Z]?)\b", re.IGNORECASE
)

# Enough surrounding text to see the real phrasing without printing the
# whole (sometimes very long) body_text back in the report.
CONTEXT_RADIUS = 40


def _context(text, start, end):
    lo = max(0, start - CONTEXT_RADIUS)
    hi = min(len(text), end + CONTEXT_RADIUS)
    return text[lo:hi]


def find_cross_reference_candidates(body_text):
    """Find candidate section/range/chapter mentions in one section's body.

    Returns a list of {"kind", "text", "context"} dicts in reading order.
    Diagnostic only: this does not decide `reference_kind` values for
    SCHEMA.md's `ors_cross_reference` table, only surfaces what is printed.
    """
    if not body_text:
        return []

    entries = []
    claimed_spans = []

    for match in RANGE_PATTERN.finditer(body_text):
        claimed_spans.append((match.start(), match.end()))
        entries.append((match.start(), {
            "kind": "range",
            "text": match.group(0),
            "context": _context(body_text, match.start(), match.end()),
        }))

    for match in SECTION_NUMBER_PATTERN.finditer(body_text):
        if any(start <= match.start() < end for start, end in claimed_spans):
            continue
        entries.append((match.start(), {
            "kind": "section",
            "text": match.group(0),
            "context": _context(body_text, match.start(), match.end()),
        }))

    for match in CHAPTER_MENTION_PATTERN.finditer(body_text):
        # The lookbehind's own \s+ is captured in the match (fixed-width
        # lookbehinds can't consume it), so the reported span starts at
        # "chapter" itself, not at the whitespace before it.
        phrase = match.group(0).lstrip()
        start = match.end() - len(phrase)
        entries.append((start, {
            "kind": "chapter",
            "text": phrase,
            "context": _context(body_text, start, match.end()),
        }))

    entries.sort(key=lambda item: item[0])
    return [entry for _, entry in entries]
