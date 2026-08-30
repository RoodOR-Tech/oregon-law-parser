#!/usr/bin/env python3
"""Measure editorial and preface notes printed within ORS section body text.

`ors_section_note` (SCHEMA.md) has so far only been filled for the
source-credit form (`ors_source_credit`, already extracted). Every
bracketed credit form observed in the sample chapters has been a
session-law citation or one of the two non-citation forms (`Formerly X`,
bare `Renumbered X`); ROADMAP.md records the editorial/preface-note form as
increment 3's one remaining unstarted item, since a genuine note distinct
from a credit had not yet been observed. The `chapter 88` cross-reference
candidate for 2025-1.002 already flagged one in passing:

    ... 2025 c.256 §6] Note: Sections 3 and 4, chapter 88, Oregon Laws
    2025, provide: Sec. 3. No...

That is a real "Note:" block printed inline in `body_text`, after the
section's own bracketed credit -- not itself a credit, and not yet stripped
out of `body_text` the way SCHEMA.md's `ors_section_note` table calls for.

This module only measures where such blocks appear and how they are
introduced (`Note:`, `Notes:`), the same discipline every earlier table in
this pipeline followed: the structure probe before the chapter parser, the
unparsed-segment count before the credit rule, the stub-line count before
the anchoring rule, the cross-reference candidates before `ors_cross_
reference` rows. What CI reports here decides the extraction rule --
where a note block actually ends, and whether `Note:` and `Notes:` need
different handling -- rather than guessing those now.
"""
import re

NOTE_INTRODUCER_PATTERN = re.compile(r"\bNotes?:\s")

# Enough surrounding text to see the real block shape without printing the
# whole (sometimes very long) body_text back in the report.
CONTEXT_RADIUS = 200


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
