#!/usr/bin/env python3
"""Parse acquired ORS chapter documents into relational rows.

Stage 4 of the ORS relational-table pipeline. Emits ors_edition, ors_chapter,
ors_subdivision and ors_section rows from the chapter documents acquired by
acquire_ors_chapters.py.

Segmentation follows what the probe measured rather than what the layout
suggests. The sources are Windows-1252 Word HTML exports with no semantic
markup, and each chapter opens with a table of contents repeating every
section number and catchline. Those contents entries are not bold; the body
headings are. Sections are therefore anchored on bold runs, not on line
position, which over-counts by roughly a factor of two.

Every row carries character offsets into the normalized chapter text, so any
row traces back to the exact span of pinned source bytes that produced it.
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ors_chapters import chapter_sort_key, parse_chapter_number  # noqa: E402
from ors_text import decode_markup, declared_charset, normalize_spaces  # noqa: E402

SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]*>")
# Tags that end a visible line in the published exports.
BLOCK_BOUNDARY_PATTERN = re.compile(
    r"^</?\s*(?:br|p|div|tr|li|h[1-6]|table|blockquote)\b", re.IGNORECASE
)
BOLD_OPEN_PATTERN = re.compile(r"^<\s*b\b", re.IGNORECASE)
BOLD_CLOSE_PATTERN = re.compile(r"^<\s*/\s*b\b", re.IGNORECASE)

# A section heading: number then catchline. An opening parenthesis marks a
# wrapped subsection citation instead, so it is excluded.
SECTION_CATCHLINE_PATTERN = re.compile(
    r"^(?P<number>\d{1,3}[A-Z]?\.\d{3})\s+(?=[A-Z])(?P<catchline>.*)$"
)
# A section printed only as a bracketed stub. The keyword is required: a
# bracket opening a year is a wrapped source credit, not a stub.
SECTION_STUB_PATTERN = re.compile(
    r"^(?P<number>\d{1,3}[A-Z]?\.\d{3})\s+(?P<stub>\[(?:Repealed|Renumbered|Amended|Formerly|Reserved)\b.*)$",
    re.IGNORECASE,
)
# A trailing bracketed group is the section's source credit. Parsing its
# contents into rows is increment 3; here it is only separated from the
# statutory text so body_text holds the text and not the history.
TRAILING_CREDIT_PATTERN = re.compile(r"(?P<credit>\[[^\[\]]*\])\s*$")
RENUMBERED_TO_PATTERN = re.compile(r"\bRenumbered\s+(?P<number>\d{1,3}[A-Z]?\.\d{3})", re.IGNORECASE)

# The chapter document names itself as "192 - Records; Public Reports and
# Meetings" and prints its edition as "2025" followed by "EDITION".
CHAPTER_HEADING_PATTERN = re.compile(
    r"^(?P<number>\d{1,3}[A-Z]?)\s*[–—-]\s*(?P<name>\S.*)$"
)
EDITION_YEAR_PATTERN = re.compile(r"^((?:19|20)\d{2})$")

# Centred headings dividing a chapter carry no section number. They appear as
# an all-capitals run or as a parenthesized phrase.
UPPER_HEADING_PATTERN = re.compile(r"^[A-Z][A-Z0-9 ,.;:'&/–—-]{2,}$")
PAREN_HEADING_PATTERN = re.compile(r"^\([A-Z][^()]{2,}\)$")
SECTION_NUMBER_ANYWHERE = re.compile(r"\d{1,3}[A-Z]?\.\d{3}")

# How far into the document the chapter heading and edition banner are sought.
HEAD_LINE_LIMIT = 40


def iter_runs(markup):
    """Yield (text, is_bold) runs, with block boundaries as newline runs.

    Bold state is tracked across the document so a section heading split into
    several bold spans is still recognized as one run of bold text.
    """
    markup = SCRIPT_STYLE_PATTERN.sub(" ", markup)
    bold_depth = 0
    cursor = 0
    for match in TAG_PATTERN.finditer(markup):
        chunk = markup[cursor:match.start()]
        if chunk:
            yield chunk, bold_depth > 0
        cursor = match.end()
        tag = match.group(0)
        if BOLD_OPEN_PATTERN.match(tag):
            bold_depth += 1
        elif BOLD_CLOSE_PATTERN.match(tag):
            bold_depth = max(0, bold_depth - 1)
        elif BLOCK_BOUNDARY_PATTERN.match(tag):
            yield "\n", bold_depth > 0
    tail = markup[cursor:]
    if tail:
        yield tail, bold_depth > 0


def normalize_chapter_text(markup):
    """Build the normalized chapter text and the bold spans within it.

    Returns (text, bold_spans) where each span is a (start, end) pair into
    text. Whitespace inside a run is collapsed and block boundaries become
    single newlines, so offsets are stable for a given source document.
    """
    pieces = []
    bold_spans = []
    length = 0
    open_bold = None

    def append(fragment):
        nonlocal length
        if not fragment:
            return
        pieces.append(fragment)
        length += len(fragment)

    for raw, is_bold in iter_runs(markup):
        # The bold transition is handled before anything else. Handling it
        # only for text runs let two adjacent bold headings separated by a
        # block boundary merge into a single span, which silently swallowed
        # the second section.
        if is_bold and open_bold is None:
            open_bold = length
        elif not is_bold and open_bold is not None:
            bold_spans.append((open_bold, length))
            open_bold = None
        if raw == "\n":
            if pieces and not pieces[-1].endswith("\n"):
                append("\n")
            continue
        text = normalize_spaces(html.unescape(raw))
        text = re.sub(r"[ \t\r\f\v]+", " ", text.replace("\n", " "))
        if not text.strip():
            # Whitespace between runs still separates words.
            if pieces and not pieces[-1].endswith((" ", "\n")):
                append(" ")
            continue
        append(text)
    if open_bold is not None:
        bold_spans.append((open_bold, length))

    # Offsets are recorded against exactly this string, so it is returned
    # unaltered: any later rewrite would invalidate every span.
    return "".join(pieces), bold_spans


def line_spans(text):
    """Yield (line, start, end) for every non-empty line of the text."""
    offset = 0
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped:
            start = offset + (len(raw) - len(raw.lstrip()))
            yield stripped, start, start + len(stripped)
        offset += len(raw) + 1


def classify_stub(stub_text):
    """Return (status, renumbered_to) for a bracketed section stub.

    A stub can record more than one event, as in "[Amended by 1961 c.160 s.4;
    repealed by 1973 c.794 s.34]". The final disposition wins, so a repeal is
    reported even when an amendment precedes it.
    """
    lowered = stub_text.lower()
    renumbered = RENUMBERED_TO_PATTERN.search(stub_text)
    if "repealed" in lowered:
        return "repealed", None
    if "renumbered" in lowered:
        return "renumbered", renumbered.group("number") if renumbered else None
    if "reserved" in lowered:
        return "reserved", None
    # An amendment-only or formerly-only stub records history but no operative
    # text, so it is a note rather than an operative section.
    return "note_only", None


def split_source_credit(body):
    """Separate a trailing bracketed source credit from the statutory text."""
    match = TRAILING_CREDIT_PATTERN.search(body)
    if match is None:
        return body.strip(), None
    return body[: match.start()].strip(), match.group("credit")


def parse_chapter_heading(lines):
    """Read the chapter number and name the document prints for itself."""
    for line, _, _ in lines[:HEAD_LINE_LIMIT]:
        match = CHAPTER_HEADING_PATTERN.match(line)
        if match is None:
            continue
        number = parse_chapter_number(match.group("number"))
        if number is None:
            continue
        return number, match.group("name").strip()
    return None, None


def parse_edition_year(lines):
    """Read the edition the document prints, as a year line then EDITION."""
    window = lines[:HEAD_LINE_LIMIT]
    for index, (line, _, _) in enumerate(window):
        match = EDITION_YEAR_PATTERN.match(line)
        if match is None:
            continue
        following = window[index + 1][0] if index + 1 < len(window) else ""
        if following.upper().startswith("EDITION"):
            return int(match.group(1))
    return None


def is_subdivision_heading(line):
    """A centred heading dividing a chapter, carrying no section number."""
    if SECTION_NUMBER_ANYWHERE.search(line):
        return False
    if PAREN_HEADING_PATTERN.match(line):
        return True
    return bool(UPPER_HEADING_PATTERN.match(line)) and any(c.isalpha() for c in line)


def parse_chapter(markup, chapter_number):
    """Parse one chapter document into edition, chapter, subdivision and section rows."""
    text, bold_spans = normalize_chapter_text(markup)
    lines = list(line_spans(text))

    printed_number, chapter_name = parse_chapter_heading(lines)
    edition_year = parse_edition_year(lines)

    # A bold run is a section anchor when its text opens with a section number
    # followed by a catchline or a bracketed disposition stub.
    anchors = []
    for start, end in bold_spans:
        run = " ".join(text[start:end].split())
        if not run:
            continue
        catchline_match = SECTION_CATCHLINE_PATTERN.match(run)
        stub_match = SECTION_STUB_PATTERN.match(run)
        if stub_match is not None:
            anchors.append({
                "number": stub_match.group("number"),
                "catchline": None,
                "stub": stub_match.group("stub"),
                "start": start,
                "headingEnd": end,
            })
        elif catchline_match is not None:
            anchors.append({
                "number": catchline_match.group("number"),
                "catchline": catchline_match.group("catchline").strip() or None,
                "stub": None,
                "start": start,
                "headingEnd": end,
            })

    anchors.sort(key=lambda item: item["start"])

    # A heading that divides no sections is not a subdivision of the body. The
    # contents list at the head of the chapter repeats the same headings above
    # unbolded entries, and the edition banner looks like one too; neither has
    # a section anchor beneath it before the next heading.
    candidates = [
        {"headingText": line, "start": start, "end": end}
        for line, start, end in lines
        if is_subdivision_heading(line)
    ]
    subdivisions = []
    for index, candidate in enumerate(candidates):
        limit = candidates[index + 1]["start"] if index + 1 < len(candidates) else len(text)
        if any(candidate["start"] < anchor["start"] < limit for anchor in anchors):
            subdivisions.append(candidate)

    sections = []
    problems = []
    seen = set()
    for index, anchor in enumerate(anchors):
        next_anchor = anchors[index + 1]["start"] if index + 1 < len(anchors) else len(text)
        # A subdivision heading between this section and the next belongs to
        # neither: it ends this section's text rather than trailing it, which
        # is what let a heading swallow the section's own source credit.
        following_heading = next(
            (item["start"] for item in subdivisions if item["start"] > anchor["start"]),
            len(text),
        )
        end = min(next_anchor, following_heading)
        number = anchor["number"]
        if number in seen:
            problems.append(f"duplicate section number in chapter: {number}")
            continue
        seen.add(number)
        if chapter_number is not None and not number.startswith(f"{chapter_number}."):
            problems.append(
                f"section {number} does not belong to chapter {chapter_number}"
            )
            continue

        if anchor["stub"] is not None:
            status, renumbered_to = classify_stub(anchor["stub"])
            # A stub section has no operative text: the bracket is the whole
            # entry, and it is history rather than statute.
            credit = anchor["stub"]
            body = text[anchor["headingEnd"]:end].strip() or None
        else:
            status, renumbered_to = "operative", None
            body, credit = split_source_credit(text[anchor["headingEnd"]:end].strip())

        # The most recent heading above this section owns it.
        owning = None
        for subdivision in subdivisions:
            if subdivision["start"] < anchor["start"]:
                owning = subdivision
            else:
                break

        sections.append({
            "sectionNumber": number,
            "catchline": anchor["catchline"],
            "bodyText": body or None,
            "sourceCreditRaw": credit,
            "status": status,
            "renumberedTo": renumbered_to,
            "subdivisionHeading": owning["headingText"] if owning else None,
            "charOffsetStart": anchor["start"],
            "charOffsetEnd": end,
        })

    return {
        "printedChapterNumber": printed_number,
        "chapterName": chapter_name,
        "editionYear": edition_year,
        "normalizedCharCount": len(text),
        "boldRunCount": len(bold_spans),
        "sections": sections,
        "subdivisions": subdivisions,
        "problems": problems,
    }


def build_rows(chapter_records, repo_root=None):
    """Turn parsed chapters into the relational rows defined in SCHEMA.md."""
    editions = {}
    chapters = []
    subdivisions = []
    sections = []
    problems = []

    for record in chapter_records:
        number = record["chapterNumber"]
        parsed = record["parsed"]
        edition_year = parsed["editionYear"]
        if edition_year is None:
            # editionId is the primary key of ors_edition and the
            # discriminator between editions in every other table, so a row
            # that cannot be filed against an edition is not emitted.
            problems.append(f"chapter {number} states no ORS edition year")
            continue
        edition_id = str(edition_year)
        editions.setdefault(edition_id, {
            "editionId": edition_id,
            "editionYear": edition_year,
            "chapterCount": 0,
        })
        editions[edition_id]["chapterCount"] += 1

        printed = parsed["printedChapterNumber"]
        if printed is not None and printed != number:
            problems.append(
                f"chapter {number} names itself {printed} in its own heading"
            )
            continue

        chapter_id = f"{edition_id}-{number}"
        chapters.append({
            "chapterId": chapter_id,
            "editionId": edition_id,
            "chapterNumber": number,
            "chapterSortKey": record["chapterSortKey"],
            "chapterName": parsed["chapterName"],
            "titleNumber": record.get("titleNumber"),
            "volumeNumber": record.get("volumeNumber"),
            "sourceUrl": record.get("sourceUrl"),
            "sourceSha256": record.get("sha256"),
            "sourceBytes": record.get("bytes"),
            "sourceEncoding": record.get("sourceEncoding"),
            "sectionCount": len(parsed["sections"]),
        })

        subdivision_ids = {}
        for ordinal, subdivision in enumerate(parsed["subdivisions"], start=1):
            subdivision_id = f"{chapter_id}-sd{ordinal:04d}"
            subdivision_ids[subdivision["start"]] = subdivision_id
            subdivisions.append({
                "subdivisionId": subdivision_id,
                "chapterId": chapter_id,
                "headingText": subdivision["headingText"],
                "ordinal": ordinal,
                "charOffsetStart": subdivision["start"],
                "charOffsetEnd": subdivision["end"],
            })

        heading_to_id = {}
        for subdivision in parsed["subdivisions"]:
            heading_to_id.setdefault(
                subdivision["headingText"], subdivision_ids[subdivision["start"]]
            )

        for ordinal, section in enumerate(parsed["sections"], start=1):
            sections.append({
                "sectionId": f"{edition_id}-{section['sectionNumber']}",
                "chapterId": chapter_id,
                "subdivisionId": heading_to_id.get(section["subdivisionHeading"]),
                "sectionNumber": section["sectionNumber"],
                "sectionSortKey": section_sort_key(section["sectionNumber"]),
                "catchline": section["catchline"],
                "bodyText": section["bodyText"],
                "sourceCreditRaw": section["sourceCreditRaw"],
                "status": section["status"],
                "renumberedTo": section["renumberedTo"],
                "ordinal": ordinal,
                "charOffsetStart": section["charOffsetStart"],
                "charOffsetEnd": section["charOffsetEnd"],
            })

        problems.extend(f"chapter {number}: {item}" for item in parsed["problems"])

    return {
        "editions": sorted(editions.values(), key=lambda item: item["editionId"]),
        "chapters": chapters,
        "subdivisions": subdivisions,
        "sections": sections,
        "problems": problems,
    }


def section_sort_key(section_number):
    """Order sections the way the statute book does, fraction included."""
    chapter_part, _, fraction = section_number.partition(".")
    return f"{chapter_sort_key(chapter_part)}.{fraction}"


def check_referential_integrity(rows):
    """The SCHEMA.md invariants, as a list of violations."""
    violations = []
    edition_ids = {item["editionId"] for item in rows["editions"]}
    chapter_ids = {item["chapterId"] for item in rows["chapters"]}
    subdivision_ids = {item["subdivisionId"] for item in rows["subdivisions"]}

    for chapter in rows["chapters"]:
        if chapter["editionId"] not in edition_ids:
            violations.append(f"chapter {chapter['chapterId']} has no edition")
        if not chapter["sourceSha256"]:
            violations.append(f"chapter {chapter['chapterId']} has no pinned digest")

    for subdivision in rows["subdivisions"]:
        if subdivision["chapterId"] not in chapter_ids:
            violations.append(f"subdivision {subdivision['subdivisionId']} has no chapter")

    seen_sections = set()
    for section in rows["sections"]:
        if section["chapterId"] not in chapter_ids:
            violations.append(f"section {section['sectionId']} has no chapter")
        if section["subdivisionId"] and section["subdivisionId"] not in subdivision_ids:
            violations.append(f"section {section['sectionId']} has a dangling subdivision")
        if section["sectionId"] in seen_sections:
            violations.append(f"duplicate section id {section['sectionId']}")
        seen_sections.add(section["sectionId"])
        chapter_number = section["chapterId"].split("-", 1)[1]
        if not section["sectionNumber"].startswith(f"{chapter_number}."):
            violations.append(
                f"section {section['sectionId']} is filed under chapter {chapter_number}"
            )
        if section["status"] not in SECTION_STATUSES:
            violations.append(
                f"section {section['sectionId']} has unknown status {section['status']}"
            )
        if section["charOffsetStart"] >= section["charOffsetEnd"]:
            violations.append(f"section {section['sectionId']} has an empty span")

    for chapter in rows["chapters"]:
        if chapter["sectionCount"] == 0:
            violations.append(f"chapter {chapter['chapterId']} produced no sections")

    return violations


SECTION_STATUSES = {"operative", "repealed", "renumbered", "reserved", "note_only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--rows", help="where to write the emitted relational rows")
    parser.add_argument("--limit", type=int, help="parse at most this many chapters")
    args = parser.parse_args(argv)

    acquisition = json.loads(Path(args.acquisition_report).read_text())
    acquired = [
        chapter for chapter in acquisition.get("chapters", [])
        if chapter.get("ok") and chapter.get("sourceFormat") == "html"
    ]
    if args.limit is not None:
        acquired = acquired[: args.limit]

    records = []
    unreadable = []
    for chapter in acquired:
        path = Path(chapter["fixture"])
        if not path.exists():
            unreadable.append({"chapterNumber": chapter["chapterNumber"], "error": "fixture missing"})
            continue
        data = path.read_bytes()
        markup, encoding = decode_markup(data, declared_charset(data))
        parsed = parse_chapter(markup, chapter["chapterNumber"])
        record = dict(chapter)
        record["sourceEncoding"] = encoding
        record["parsed"] = parsed
        record["chapterSortKey"] = chapter.get("chapterSortKey") or chapter_sort_key(
            chapter["chapterNumber"]
        )
        records.append(record)

    rows = build_rows(records)
    violations = check_referential_integrity(rows)

    report = {
        "schemaVersion": 1,
        "stage": "parse",
        "parsedChapterCount": len(records),
        "unreadableChapterCount": len(unreadable),
        "editionCount": len(rows["editions"]),
        "chapterRowCount": len(rows["chapters"]),
        "subdivisionRowCount": len(rows["subdivisions"]),
        "sectionRowCount": len(rows["sections"]),
        "statusCounts": status_counts(rows["sections"]),
        "problems": rows["problems"],
        "integrityViolations": violations,
        "unreadable": unreadable,
        "valid": bool(rows["sections"]) and not rows["problems"] and not violations and not unreadable,
        "perChapter": [
            {
                "chapterNumber": chapter["chapterNumber"],
                "chapterName": chapter["chapterName"],
                "titleNumber": chapter["titleNumber"],
                "sectionCount": chapter["sectionCount"],
            }
            for chapter in rows["chapters"]
        ],
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    if args.rows:
        Path(args.rows).write_text(json.dumps(rows, indent=2) + "\n")

    print(json.dumps({
        "valid": report["valid"],
        "parsedChapterCount": report["parsedChapterCount"],
        "editionCount": report["editionCount"],
        "sectionRowCount": report["sectionRowCount"],
        "subdivisionRowCount": report["subdivisionRowCount"],
        "statusCounts": report["statusCounts"],
        "problemCount": len(report["problems"]),
        "integrityViolationCount": len(violations),
    }, indent=2))
    return 0 if report["valid"] else 1


def status_counts(sections):
    counts = {}
    for section in sections:
        counts[section["status"]] = counts.get(section["status"], 0) + 1
    return dict(sorted(counts.items()))


if __name__ == "__main__":
    sys.exit(main())
