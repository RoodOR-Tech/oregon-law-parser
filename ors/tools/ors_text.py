#!/usr/bin/env python3
"""Shared text handling for ORS source documents.

The published chapter documents are Microsoft Word HTML exports encoded in
Windows-1252, not UTF-8. Decoding them as UTF-8 turns every section symbol,
em dash and non-breaking space into a replacement character, which silently
corrupts both the statutory text and the structural signals used to segment
it. Decoding is therefore explicit and shared, not left to each tool.
"""
import re

# Word HTML declares its charset in a meta tag. Read it from the raw bytes,
# which are ASCII-compatible in every encoding this matters for.
META_CHARSET_PATTERN = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_-]+)""",
    re.IGNORECASE,
)

# Word exports are Windows-1252. Latin-1 would decode without error but would
# mis-map the 0x80-0x9F range, where the section symbol's neighbours live.
DEFAULT_HTML_ENCODING = "cp1252"

NON_BREAKING_SPACE = " "


def declared_charset(data):
    """Return the charset the document declares, or None."""
    match = META_CHARSET_PATTERN.search(data[:8192])
    if match is None:
        return None
    return match.group(1).decode("ascii", errors="replace").lower()


def decode_markup(data, declared=None):
    """Decode source bytes to text, reporting which encoding was used.

    Returns (text, encoding_used). A declared charset wins. Otherwise UTF-8 is
    tried strictly, because a document that decodes cleanly as UTF-8 almost
    certainly is UTF-8, and Windows-1252 is the fallback. Decoding never
    raises: a document that resists every candidate is decoded with
    replacement so the failure surfaces as visible damage in the probe rather
    than as a crash.
    """
    candidates = []
    if declared:
        candidates.append(declared)
    candidates.extend(["utf-8", DEFAULT_HTML_ENCODING])
    for encoding in candidates:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode(DEFAULT_HTML_ENCODING, errors="replace"), "cp1252-replace"


def normalize_spaces(text):
    """Collapse the non-breaking spaces Word uses as layout padding.

    The chapter documents separate a section number from its catchline with a
    run of non-breaking spaces, not ordinary whitespace. Treating them as
    whitespace is what lets a single rule match both the printed layout and
    ordinary prose.
    """
    return text.replace(NON_BREAKING_SPACE, " ")
