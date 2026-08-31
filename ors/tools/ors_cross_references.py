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

`resolve_cross_references` turns the measured candidates into SCHEMA.md's
`ors_cross_reference` rows. SCHEMA.md already commits to the shape: a
`range` candidate becomes two rows (`range_start` and `range_end`, one per
endpoint, not a single `range` kind); `to_section_id` stays null "rather
than being dropped" for a citation SCHEMA.md's own example calls out --
one to a repealed or never-existing section -- and the fixed seven-chapter
sample makes most real citations look exactly like that: a citation to a
section outside the sample chapters cannot resolve within this build no
matter how real the reference is, only a whole-edition build resolves it.
A `chapter` candidate can never resolve to one specific section, so its
`to_section_id` is always null -- not a resolution failure, just outside
what this table's own foreign key can point at.
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

    Returns a list of dicts in reading order, each carrying "kind", "text"
    and "context" (as before this function fed resolution too), plus
    "charOffsetStart"/"charOffsetEnd" relative to `body_text` and whatever
    structured fields `resolve_cross_references` needs for that kind:
    "startNumber"/"endNumber" for a range, "number" for a chapter. A bare
    section candidate's own `to_section_number` is just its "text".
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
            "startNumber": match.group("start"),
            "endNumber": match.group("end"),
            "charOffsetStart": match.start(),
            "charOffsetEnd": match.end(),
            "context": _context(body_text, match.start(), match.end()),
        }))

    for match in SECTION_NUMBER_PATTERN.finditer(body_text):
        if any(start <= match.start() < end for start, end in claimed_spans):
            continue
        entries.append((match.start(), {
            "kind": "section",
            "text": match.group(0),
            "charOffsetStart": match.start(),
            "charOffsetEnd": match.end(),
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
            "number": match.group("number"),
            "charOffsetStart": start,
            "charOffsetEnd": match.end(),
            "context": _context(body_text, start, match.end()),
        }))

    entries.sort(key=lambda item: item[0])
    return [entry for _, entry in entries]


def resolve_cross_references(candidates, section_ids_by_number):
    """Turn measured candidates into `ors_cross_reference` rows.

    `candidates` is a list of {"sectionId", ...} dicts -- each of
    `find_cross_reference_candidates`'s own dicts with a "sectionId" key
    added, in reading order per section (candidates from different
    sections may be interleaved; each section's own candidates are
    ordered by the caller, matching `charOffsetStart`). `section_ids_by_
    number` maps a section number to its `ors_section.section_id`, scoped
    to whatever edition(s) the caller has already parsed -- a number
    outside that map resolves to `to_section_id = None`, real data per
    SCHEMA.md's own note, not a defect in this function.

    A `range` candidate becomes two rows, `range_start` then `range_end`,
    both sharing the range's own span (SCHEMA.md gives each endpoint its
    own row, not a combined `range` kind). Ordinal numbering is per
    `from_section_id`, restarting at each new section, in the order
    `candidates` presents that section's own entries.
    """
    rows = []
    ordinal_by_section = {}

    def next_ordinal(section_id):
        ordinal_by_section[section_id] = ordinal_by_section.get(section_id, 0) + 1
        return ordinal_by_section[section_id]

    def append_row(section_id, to_section_number, reference_kind, start, end):
        ordinal = next_ordinal(section_id)
        rows.append({
            "referenceId": f"{section_id}-x{ordinal:04d}",
            "fromSectionId": section_id,
            "toSectionNumber": to_section_number,
            "toSectionId": section_ids_by_number.get(to_section_number),
            "referenceKind": reference_kind,
            "ordinal": ordinal,
            "charOffsetStart": start,
            "charOffsetEnd": end,
        })

    for candidate in candidates:
        section_id = candidate["sectionId"]
        start, end = candidate["charOffsetStart"], candidate["charOffsetEnd"]
        if candidate["kind"] == "range":
            append_row(section_id, candidate["startNumber"], "range_start", start, end)
            append_row(section_id, candidate["endNumber"], "range_end", start, end)
        elif candidate["kind"] == "section":
            append_row(section_id, candidate["text"], "section", start, end)
        elif candidate["kind"] == "chapter":
            ordinal = next_ordinal(section_id)
            rows.append({
                "referenceId": f"{section_id}-x{ordinal:04d}",
                "fromSectionId": section_id,
                "toSectionNumber": candidate["number"],
                # A chapter reference names no single section, so it can
                # never resolve here -- SCHEMA.md's ors_cross_reference has
                # no to_chapter_id for it to point at instead.
                "toSectionId": None,
                "referenceKind": "chapter",
                "ordinal": ordinal,
                "charOffsetStart": start,
                "charOffsetEnd": end,
            })

    return rows
