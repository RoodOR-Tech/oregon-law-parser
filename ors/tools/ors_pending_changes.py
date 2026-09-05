"""Extract a chapter's own printed notice of pending session-law changes.

Increment 6, part 1 (see ROADMAP.md): a chapter document already prints, in
its own front matter, that later session laws have already changed it ahead
of the next edition being published -- see FINDINGS.md's "Chapters
advertise pending changes". Confirmed directly against the real, frozen
increment 5 gold chapters (three of the five -- 183, 471 and 659A; 12 and
105 print neither notice) in exactly three distinct printed shapes, each
naming the 2026 session:

  ORS sections in this chapter were amended or repealed by the Legislative
  Assembly during its 2026 regular session. See the table of ORS sections
  amended or repealed during the 2026 regular session: 2026 A&R Tables

  New sections of law were added by legislative action to this ORS chapter
  or to a series within this ORS chapter by the Legislative Assembly during
  its 2026 regular session. See sections in the following 2026 Oregon Laws
  chapters: 2026 Session Laws 0050; 2026 Session Laws 0104; 2026 Session
  Laws 0105

  New sections of law were enacted by the Legislative Assembly during its
  2026 regular session and pertain to or are likely to be compiled in this
  ORS chapter. See sections in the following 2026 Oregon Laws chapters:
  2026 Session Laws 0093; 2026 Session Laws 0126

The first names no specific Oregon Laws chapter -- it only points at that
year's consolidated A&R (amended/repealed) table -- so it produces one row
with `sessionLawChapter` left null. The other two each name one or more
Oregon Laws chapters directly, in the exact (session_year, session_law_
chapter) shape `ors_credits.py` already parses out of a section's own
citations, so each named chapter becomes its own row: a printed join to the
amendment parser's `(year, chapter)` output, per ROADMAP.md and FINDINGS.md.

A chapter list can print in either of two real shapes: every chapter fully
qualified ("2026 Session Laws 0050; 2026 Session Laws 0104"), as in every
gold-chapter example above, or -- per FINDINGS.md's own earlier "Chapters
advertise pending changes" fragment -- only the first chapter qualified and
the rest bare, semicolon-separated numbers ("2026 Session Laws 0011; 0017;
0085; 0096"). `_session_law_chapters` tries both forms per segment so
either shape yields every chapter named, not just the first.

Each notice prints as its own paragraph in the source, which
`normalize_chapter_text` already collapses to a single line regardless of
how it wraps in the raw markup -- confirmed directly against the real,
frozen chapter bytes rather than assumed, the same discipline every earlier
module in this pipeline follows.
"""
import re

AR_TABLE_NOTICE_PATTERN = re.compile(
    r"ORS sections in this chapter were amended or repealed by the "
    r"Legislative Assembly during its (?P<year>(?:18|19|20)\d{2}) regular "
    r"session\. See the table of ORS sections amended or repealed during "
    r"the (?P=year) regular session: (?P=year) A&R Tables"
)
NEW_SERIES_SECTION_NOTICE_PATTERN = re.compile(
    r"New sections of law were added by legislative action to this ORS "
    r"chapter or to a series within this ORS chapter by the Legislative "
    r"Assembly during its (?P<year>(?:18|19|20)\d{2}) regular session\. See "
    r"sections in the following (?P=year) Oregon Laws chapters: "
    r"(?P<chapters>.+)$"
)
NEW_COMPILED_SECTION_NOTICE_PATTERN = re.compile(
    r"New sections of law were enacted by the Legislative Assembly during "
    r"its (?P<year>(?:18|19|20)\d{2}) regular session and pertain to or "
    r"are likely to be compiled in this ORS chapter\. See sections in the "
    r"following (?P=year) Oregon Laws chapters: (?P<chapters>.+)$"
)
# Real notices zero-pad the chapter number ("Session Laws 0057"), unlike an
# ordinary source credit's own "c.57" -- stripped here by \d+'s own leading
# zeros never surviving int().
#
# Two real shapes exist for a list of more than one chapter. Every chapter
# 183/471/659A notice repeats the full citation for every item ("2026
# Session Laws 0050; 2026 Session Laws 0104; 2026 Session Laws 0105"), but
# FINDINGS.md's own "Chapters advertise pending changes" records a second,
# abbreviated real form where only the first item is fully qualified and
# the rest are bare, semicolon-separated numbers ("2026 Session Laws 0011;
# 0017; 0085; 0096") -- a Codex review of this module's first version
# confirmed the fully-qualified-only pattern silently dropped every chapter
# after the first in that shape, losing three of four real join keys.
SESSION_LAW_CHAPTER_FULL_PATTERN = re.compile(
    r"^(?:18|19|20)\d{2}\s+Session Laws\s+0*(?P<chapter>\d+)$"
)
SESSION_LAW_CHAPTER_BARE_PATTERN = re.compile(r"^0*(?P<chapter>\d+)$")


def _session_law_chapters(chapters_text):
    """Parse one or more Oregon Laws chapter numbers from a notice's own
    trailing, semicolon-separated list -- see the patterns' own comment for
    the two real shapes this handles."""
    chapters = []
    for segment in chapters_text.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        match = (
            SESSION_LAW_CHAPTER_FULL_PATTERN.match(segment)
            or SESSION_LAW_CHAPTER_BARE_PATTERN.match(segment)
        )
        if match is not None:
            chapters.append(int(match.group("chapter")))
    return chapters

# (change_kind, pattern). Order does not matter: the three notices are
# textually distinct enough that at most one pattern ever matches a given
# line, confirmed against every real notice line found in the gold chapters.
NOTICE_PATTERNS = (
    ("amended_or_repealed_elsewhere", AR_TABLE_NOTICE_PATTERN),
    ("new_series_section", NEW_SERIES_SECTION_NOTICE_PATTERN),
    ("new_compiled_section", NEW_COMPILED_SECTION_NOTICE_PATTERN),
)


def find_pending_change_notices(lines):
    """Return one row per (change_kind, session_year, session_law_chapter)
    a chapter document's own front matter names, in document order.

    `lines` is parse_ors_chapter.py's own (line, start, end) triples over
    the chapter's normalized text. A notice naming one or more Oregon Laws
    chapters becomes one row per chapter named, all sharing that notice's
    own raw text and char offsets (the whole printed line); the A&R-table
    notice names no specific chapter, so it becomes a single row with
    `sessionLawChapter` left null.
    """
    found = []
    for line, start, end in lines:
        for change_kind, pattern in NOTICE_PATTERNS:
            match = pattern.search(line)
            if match is None:
                continue
            year = int(match.group("year"))
            if change_kind == "amended_or_repealed_elsewhere":
                chapters = [None]
            else:
                chapters = _session_law_chapters(match.group("chapters"))
            for chapter in chapters:
                found.append({
                    "changeKind": change_kind,
                    "sessionYear": year,
                    "sessionLawChapter": chapter,
                    "noticeText": line,
                    "charOffsetStart": start,
                    "charOffsetEnd": end,
                })
            break
    return found
