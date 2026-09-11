"""Closed bracket notes are bounded spans, not the remainder of a section."""
import re
from datetime import datetime

BRACKET_START = re.compile(
    r"\[\s*(?:Series\s+enacted\s+into\s+law\s+but\s+not\s+added\s+to\s+ORS\b|"
    r"(?:18|19|20|21)\d{2}\s+c\.\s*\d+\s+§\s*\w+\s+(?:amends?|repeals?|adds?)\s+ORS\b)", re.I)


def split_bracket_notes(text):
    notes, spans = [], []
    for match in BRACKET_START.finditer(text):
        if spans and match.start() < spans[-1][1]:
            continue
        depth, end = 0, None
        for pos in range(match.start(), len(text)):
            if text[pos] == "[":
                depth += 1
            elif text[pos] == "]":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break
        if end is None:
            raise ValueError("unterminated statutory note")
        notes.append({"text": text[match.start():end], "start": match.start(), "end": end})
        spans.append((match.start(), end))
    cursor, chunks = 0, []
    for start, end in spans:
        chunks.append(text[cursor:start])
        cursor = end
    chunks.append(text[cursor:])
    return " ".join("".join(chunks).split()), notes


def explicit_effective_date(text):
    match = re.search(r"\b(?:effective(?:\s+date)?|takes\s+effect)\s+(?:on\s+)?([A-Z][a-z]+\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})", text, re.I)
    if not match:
        return None
    value = " ".join(match[1].split())
    for fmt in ("%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"invalid explicit effective date: {value}")
