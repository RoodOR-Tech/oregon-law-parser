#!/usr/bin/env python3
"""Fingerprint acquired ORS chapter markup.

Stage 3 of the ORS relational-table pipeline. This tool exists so that parsing
rules are written against the structure the authoritative source actually
publishes, rather than against an assumed layout.

It emits a structural fingerprint — tag and class histograms, counts of
candidate section numbers, bracketed source credits and repeal stubs, plus a
bounded sample of visible lines — for each acquired chapter. The sample is
capped so the report is a structural probe, not a bulk copy of the statute text.
"""
import argparse
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Candidate ORS section number as printed: chapter number, optional letter,
# a period, then exactly three digits. 279A.050 and 161.005 both match.
SECTION_NUMBER_PATTERN = re.compile(r"\b(\d{1,3}[A-Z]?)\.(\d{3})\b")
# A line that merely opens with a section number is not necessarily a section
# start: wrapped statutory text routinely begins with the tail of a cited range,
# as in "161.055, unless the context requires otherwise:". The stricter anchor
# additionally requires the number to be followed by a catchline or a bracketed
# stub. The probe measures both so the gap between them can be reviewed before a
# segmentation rule is chosen.
SECTION_LINE_PATTERN = re.compile(r"^\d{1,3}[A-Z]?\.\d{3}\b")
SECTION_ANCHOR_PATTERN = re.compile(r"^\d{1,3}[A-Z]?\.\d{3}[ \t]+(?=[A-Z\[(])")
# A printed source credit: [1971 c.743 s.1; 1973 c.836 s.339]
SOURCE_CREDIT_PATTERN = re.compile(r"\[[^\[\]]{0,400}?\bc\.\s*\d+[^\[\]]{0,400}?\]")
SESSION_CITE_PATTERN = re.compile(r"\b((?:18|19|20)\d{2})\s*c\.\s*(\d+)")
REPEAL_STUB_PATTERN = re.compile(r"\[(?:Repealed|Renumbered|Amended|Formerly)\b", re.IGNORECASE)
TAG_PATTERN = re.compile(r"<\s*([A-Za-z][A-Za-z0-9]*)\b")
CLASS_PATTERN = re.compile(r"""class\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
TAG_STRIP_PATTERN = re.compile(r"<[^>]+>")

MAX_SAMPLE_LINES = 60
MAX_SAMPLE_LINE_CHARS = 160
MAX_HISTOGRAM_ENTRIES = 25


def visible_lines(markup):
    """Reduce HTML to visible text lines, preserving block boundaries."""
    text = SCRIPT_STYLE_PATTERN.sub(" ", markup)
    text = re.sub(r"<\s*(br|/p|/div|/tr|/li|/h[1-6])\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = TAG_STRIP_PATTERN.sub("", text)
    text = html.unescape(text)
    text = text.replace(" ", " ")
    lines = []
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if line:
            lines.append(line)
    return lines


def histogram(counter, limit=MAX_HISTOGRAM_ENTRIES):
    return [
        {"value": value, "count": count}
        for value, count in counter.most_common(limit)
    ]


def probe_markup(markup, chapter_number=None):
    lines = visible_lines(markup)
    joined = "\n".join(lines)

    section_numbers = []
    for match in SECTION_NUMBER_PATTERN.finditer(joined):
        section_numbers.append(f"{match.group(1)}.{match.group(2)}")

    in_chapter = None
    if chapter_number is not None:
        prefix = f"{chapter_number}."
        in_chapter = sum(1 for number in section_numbers if number.startswith(prefix))

    credits = SOURCE_CREDIT_PATTERN.findall(joined)
    session_cites = SESSION_CITE_PATTERN.findall(joined)

    section_number_lines = [line for line in lines if SECTION_LINE_PATTERN.match(line)]
    section_anchor_lines = [line for line in lines if SECTION_ANCHOR_PATTERN.match(line)]
    anchors = set(section_anchor_lines)
    ambiguous_lines = [line for line in section_number_lines if line not in anchors]

    return {
        "visibleLineCount": len(lines),
        "visibleCharCount": len(joined),
        "tagHistogram": histogram(Counter(
            tag.lower() for tag in TAG_PATTERN.findall(markup)
        )),
        "classHistogram": histogram(Counter(
            value.strip() for attr in CLASS_PATTERN.findall(markup)
            for value in attr.split()
            if value.strip()
        )),
        "sectionNumberMatches": len(section_numbers),
        "distinctSectionNumbers": len(set(section_numbers)),
        "sectionNumbersInThisChapter": in_chapter,
        "sectionNumberLineCount": len(section_number_lines),
        "sectionAnchorLineCount": len(section_anchor_lines),
        "ambiguousSectionLineCount": len(ambiguous_lines),
        "sourceCreditMatches": len(credits),
        "sessionCitationMatches": len(session_cites),
        "repealStubMatches": len(REPEAL_STUB_PATTERN.findall(joined)),
        "sampleSectionAnchorLines": [
            line[:MAX_SAMPLE_LINE_CHARS] for line in section_anchor_lines[:10]
        ],
        "sampleAmbiguousSectionLines": [
            line[:MAX_SAMPLE_LINE_CHARS] for line in ambiguous_lines[:10]
        ],
        "sampleSourceCredits": [credit[:MAX_SAMPLE_LINE_CHARS] for credit in credits[:10]],
        "sampleLines": [line[:MAX_SAMPLE_LINE_CHARS] for line in lines[:MAX_SAMPLE_LINES]],
    }


def load_chapter_records(acquisition_report):
    report = json.loads(Path(acquisition_report).read_text())
    return [
        chapter for chapter in report.get("chapters", [])
        if chapter.get("ok") and chapter.get("fixture")
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition-report", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--limit", type=int, help="probe at most this many chapters")
    args = parser.parse_args(argv)

    chapters = load_chapter_records(args.acquisition_report)
    if args.limit is not None:
        chapters = chapters[: args.limit]

    probes = []
    unreadable = []
    for chapter in chapters:
        path = Path(chapter["fixture"])
        if not path.exists():
            unreadable.append({
                "chapterNumber": chapter["chapterNumber"],
                "fixture": str(path),
                "error": "fixture missing",
            })
            continue
        if chapter.get("sourceFormat") != "html":
            # PDF chapters need a text extraction step before a markup probe
            # means anything. Record them rather than probing them wrongly.
            unreadable.append({
                "chapterNumber": chapter["chapterNumber"],
                "fixture": str(path),
                "error": f"unsupported probe format: {chapter.get('sourceFormat')}",
            })
            continue
        markup = path.read_bytes().decode("utf-8", errors="replace")
        probe = probe_markup(markup, chapter["chapterNumber"])
        probe.update({
            "chapterNumber": chapter["chapterNumber"],
            "sourceUrl": chapter.get("sourceUrl"),
            "sha256": chapter.get("sha256"),
            "bytes": chapter.get("bytes"),
        })
        probes.append(probe)

    report = {
        "schemaVersion": 1,
        "stage": "probe",
        "probedChapterCount": len(probes),
        "unreadableChapterCount": len(unreadable),
        "valid": bool(probes) and not unreadable,
        "chapters": probes,
        "unreadable": unreadable,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "valid": report["valid"],
        "probedChapterCount": report["probedChapterCount"],
        "unreadableChapterCount": report["unreadableChapterCount"],
    }, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
