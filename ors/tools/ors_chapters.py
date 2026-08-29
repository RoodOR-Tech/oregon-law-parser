#!/usr/bin/env python3
"""Shared ORS chapter-number handling.

Chapter numbers are text, not integers: the statute book uses lettered
chapters such as 279A and 646A. These helpers are shared by roster discovery
and by acquisition so both order and address chapters identically.
"""
import re

CHAPTER_URL_TEMPLATE = "https://www.oregonlegislature.gov/bills_laws/ors/ors{chapter_file}.html"
CHAPTER_NUMBER_PATTERN = re.compile(r"^(?P<digits>\d{1,3})(?P<letter>[A-Za-z]?)$")


def normalize_chapter_number(digits, letter):
    """Return the chapter number as printed: no leading zeros, upper-case suffix."""
    return f"{int(digits)}{letter.upper()}"


def parse_chapter_number(raw):
    """Normalize a chapter number, or return None when it is not one."""
    match = CHAPTER_NUMBER_PATTERN.match(raw.strip())
    if match is None:
        return None
    return normalize_chapter_number(match.group("digits"), match.group("letter"))


def chapter_sort_key(chapter_number):
    """Order chapters the way the statute book does: 1 < 36A < 97 < 279A < 279B."""
    match = CHAPTER_NUMBER_PATTERN.match(chapter_number)
    if match is None:
        # Unparseable chapter numbers sort last rather than raising, so one
        # malformed roster entry cannot abort a whole-edition acquisition.
        return "999999~"
    return f"{int(match.group('digits')):06d}{(match.group('letter') or ' ').upper()}"


def chapter_file_stem(chapter_number):
    """Map a chapter number to its published file stem, e.g. 279A -> 279A."""
    match = CHAPTER_NUMBER_PATTERN.match(chapter_number)
    if match is None:
        raise ValueError(f"invalid chapter number: {chapter_number}")
    return f"{int(match.group('digits')):03d}{(match.group('letter') or '').upper()}"


def chapter_url(chapter_number, template=None):
    return (template or CHAPTER_URL_TEMPLATE).format(
        chapter_file=chapter_file_stem(chapter_number)
    )
