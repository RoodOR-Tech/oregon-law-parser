#!/usr/bin/env python3
"""Extract editorial notes printed within ORS section text into their own rows.

`ors_section_note` (SCHEMA.md) had so far only been filled for the
source-credit form (`ors_source_credit`, already extracted). This module's
own measurement pass, run first against the real sample chapters per this
project's usual discipline, found 152 real "Note:"/"Notes:" blocks and
three distinct resolvable shapes rather than free text (see FINDINGS.md
for the verbatim forms): a "series membership" note naming an ORS chapter
or range, a "See note under NNN.NNN" cross-reference to another section's
already-printed note, and a quoted uncodified session-law provision. The
2025-1.002 fragment that first surfaced this is typical:

    ... 2025 c.256 §6] Note: Sections 3 and 4, chapter 88, Oregon Laws
    2025, provide: Sec. 3. No...

That measurement also settled the one open question extraction needed: how
far a note block runs. Every real example -- including 2025-90.321's own
two consecutive blocks -- has one note's own text ending exactly where the
next "Note:"/"Notes:" introducer begins, or at the end of the section's
text if it is the last (or only) one. `split_editorial_notes` uses that
rule to split zero or more note blocks off a section's raw printed text
(the same raw span `split_source_credit` receives, before it strips a
credit out), leaving the remainder for the existing credit/body split
untouched. Sub-classifying the three shapes into distinct `note_kind`
values is not attempted yet -- SCHEMA.md's enum only has `editorial_note`
for this case, and further splitting the shapes apart is deferred until
there is a use for it.
"""
import re

NOTE_INTRODUCER_PATTERN = re.compile(r"\bNotes?:\s")

# Enough surrounding text to see the real block shape without printing the
# whole (sometimes very long) body_text back in the report.
CONTEXT_RADIUS = 200


def split_editorial_notes(raw_text):
    """Split trailing editorial-note blocks off the end of one section's raw text.

    A note block runs from its own introducer up to the next note
    introducer, or to the end of `raw_text` if it is the last (or only)
    one -- the rule real forms settled, per this module's docstring.

    Returns (remainder, notes). `remainder` is everything before the first
    note introducer, left unstripped exactly like `raw_text` itself so a
    caller that already strips its own input (`split_source_credit` does)
    sees no behavior change when there are no notes to split off. `notes`
    is a list of {"text", "charOffsetStart", "charOffsetEnd"} dicts in
    reading order, with offsets relative to the start of `raw_text` --
    the caller adds its own base offset to place them in the chapter's own
    normalized text, the same as every other row's offsets already do.
    """
    matches = list(NOTE_INTRODUCER_PATTERN.finditer(raw_text))
    if not matches:
        return raw_text, []

    remainder = raw_text[: matches[0].start()]
    notes = []
    for index, match in enumerate(matches):
        block_start = match.start()
        block_end = (
            matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        )
        block = raw_text[block_start:block_end]
        stripped = block.strip()
        if not stripped:
            continue
        leading = len(block) - len(block.lstrip())
        trailing = len(block) - len(block.rstrip())
        notes.append({
            "text": stripped,
            "charOffsetStart": block_start + leading,
            "charOffsetEnd": block_end - trailing,
        })
    return remainder, notes


def find_editorial_note_candidates(body_text):
    """Find candidate editorial/preface note introductions in one section.

    Returns a list of {"introducer", "context"} dicts in reading order.
    Diagnostic only: this does not decide `note_kind` values or where a
    block ends for SCHEMA.md's `ors_section_note` table, only surfaces
    where and how such blocks are introduced.
    """
    if not body_text:
        return []

    candidates = []
    for match in NOTE_INTRODUCER_PATTERN.finditer(body_text):
        hi = min(len(body_text), match.end() + CONTEXT_RADIUS)
        candidates.append({
            "introducer": match.group(0).strip(),
            "context": body_text[match.start():hi],
        })
    return candidates
