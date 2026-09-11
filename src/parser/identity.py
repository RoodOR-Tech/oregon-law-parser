"""Identity comes from publication statements, never directory names."""
import re

YEAR = r"(?:18|19|20|21)\d{2}"
EDITION = re.compile(rf"\b({YEAR})\s+(?:ORS\s+)?EDITION\b|\b(?:ORS\s+)?EDITION\s*[:\-]?\s*({YEAR})\b", re.I)
SUPPLEMENT = re.compile(rf"\b({YEAR})\s+(?:(\d+)(?:st|nd|rd|th)?\s+)?(special|regular)\s+session\b", re.I)


def edition_identity(text, expected=None):
    years = {int(m[1] or m[2]) for m in EDITION.finditer(text)}
    if len(years) != 1:
        raise ValueError(f"expected one printed edition identity, found {sorted(years)}")
    year = years.pop()
    if expected is not None and year != expected:
        raise ValueError(f"edition mismatch: requested {expected}, source prints {year}")
    supplements = sorted({(int(m[1]), m[3].lower(), int(m[2] or 1) if m[3].lower() == "special" else 0)
                          for m in SUPPLEMENT.finditer(text)})
    return {"edition_year": year, "supplements": [
        {"session_year": y, "session_kind": kind, "special_session": ordinal}
        for y, kind, ordinal in supplements if y >= year]}
