#!/usr/bin/env python3
"""Read the published ORS table of titles.

The ORS landing page does not link chapters. Its 115 links under
bills_laws/ors are the annual amendment-and-repeal reference PDFs (1941
through 2025, special sessions included), OCLA.pdf, and the alphabetical
General Index.

ORS_TitlesChapters.pdf, linked from the same page, is a TABLE OF TITLES. It
lists volumes, titles and the chapter RANGE each title covers:

    Volume 1
    Title 1 Courts of Record; Court Officers; Juries - Chs. 1-10
    2 Procedure in Civil Proceedings - Chs. 12-25
    5 Small Claims Department of Circuit Court - Ch. 46

It does not enumerate chapters. This tool therefore reads what the document
actually publishes -- ors_volume and ors_title rows, with each title's chapter
range -- and does not pretend to produce a chapter roster.

Those ranges are still load-bearing: a chapter acquired from anywhere else can
be checked against them, so a chapter filed under no published title is
visible rather than silently accepted.
"""
import argparse
import hashlib
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ors_chapters import chapter_sort_key, chapter_url, parse_chapter_number  # noqa: E402

DEFAULT_ROSTER_URL = (
    "https://www.oregonlegislature.gov/bills_laws/BillsLawsEDL/ORS_TitlesChapters.pdf"
)
USER_AGENT = "oregon-law-parser-ors-table/1"

# A volume header introduces the titles bound in that volume.
VOLUME_PATTERN = re.compile(r"^Volume\s+(?P<number>\d{1,2})$", re.IGNORECASE)

# A title line is a number, a name, then an en- or em-dash and the chapter
# range the title covers. Only the first title in each volume carries the
# literal word "Title"; the rest are bare numbers, which is exactly why a
# pattern that accepts a bare leading number as a chapter misreads them.
# Requiring the dash-and-range suffix is what separates a title line from a
# stray sidebar label such as "LANDLORD-TENANT".
TITLE_PATTERN = re.compile(
    r"^(?:Title\s+)?(?P<number>\d{1,3}[A-Z]?)\s+"
    r"(?P<name>.+?)\s*[\u2013\u2014]\s*Chs?\.\s*(?P<range>[0-9A-Za-z]+(?:\s*[-\u2013\u2014]\s*[0-9A-Za-z]+)?)\s*$"
)

# A title entry whose name is too long for one line wraps, leaving the number
# and the start of the name on one line and the rest plus the range on the
# next. Both halves must be recognized or the title is dropped silently.
TITLE_HEAD_PATTERN = re.compile(
    r"^(?:Title\s+)?(?P<number>\d{1,3}[A-Z]?)\s+(?P<name>\S.*?)\s*$"
)
TITLE_TAIL_PATTERN = re.compile(
    r"^(?P<name>\S.*?)\s*[\u2013\u2014]\s*Chs?\.\s*"
    r"(?P<range>[0-9A-Za-z]+(?:\s*[-\u2013\u2014]\s*[0-9A-Za-z]+)?)\s*$"
)

# A range endpoint is a chapter number, possibly lettered.
RANGE_PATTERN = re.compile(
    r"^(?P<first>\d{1,3}[A-Za-z]?)(?:\s*[-\u2013\u2014]\s*(?P<last>\d{1,3}[A-Za-z]?))?$"
)

# The table of titles carries no edition banner, but this stays so an edition
# statement is captured if the document ever gains one.
EDITION_PATTERN = re.compile(r"((?:19|20)\d{2})\s*EDITION", re.IGNORECASE)

MAX_SAMPLE_LINES = 40
MAX_SAMPLE_LINE_CHARS = 120


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_bytes(url, retries, timeout):
    context = ssl.create_default_context()
    last_error = None
    status = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
                status = getattr(response, "status", None)
                return response.read(), status, attempt, None
        except urllib.error.HTTPError as exc:
            status = exc.code
            last_error = f"{url}: HTTP {exc.code}"
            if exc.code == 404:
                return None, status, attempt, last_error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{url}: {exc}"
        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 8))
    return None, status, retries, last_error or "unknown download error"


def extract_text(pdf_path, tika_jar, java="java", timeout=600):
    """Extract plain text from a PDF using the vendored Tika jar."""
    result = subprocess.run(
        [java, "-jar", str(tika_jar), "--text", str(pdf_path)],
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"tika failed with exit {result.returncode}: {stderr[:500]}")
    return result.stdout.decode("utf-8", errors="replace")


def detect_edition_year(text):
    years = [int(match) for match in EDITION_PATTERN.findall(text)]
    years = [year for year in years if 1953 <= year <= 2100]
    return max(years) if years else None


def parse_chapter_range(raw):
    """Parse a printed chapter range into normalized first and last numbers."""
    match = RANGE_PATTERN.match(raw.strip())
    if match is None:
        return None
    first = parse_chapter_number(match.group("first"))
    if first is None:
        return None
    last = parse_chapter_number(match.group("last")) if match.group("last") else first
    if last is None:
        return None
    return {
        "firstChapter": first,
        "lastChapter": last,
        "firstChapterSortKey": chapter_sort_key(first),
        "lastChapterSortKey": chapter_sort_key(last),
    }


def parse_table_of_titles(text):
    """Parse volumes and titles out of the published table of titles.

    Returns (volumes, titles, unparsed_lines, unresolved_lines). A title whose
    name is too long for one line wraps, so a number-led line carrying no
    range is held and joined to the following line when that line completes
    the entry.

    A number-led line that never resolves into a title is reported as
    unresolved. Without that, a title the parser fails to recognize simply
    vanishes: the real document's title 19 was dropped exactly this way, and
    nothing in the output said so until a chapter it covers could not be
    attributed.
    """
    volumes = []
    titles = []
    unparsed = []
    unresolved = []
    seen_titles = set()
    current_volume = None
    pending = None

    def record(number, name, raw_range, source_line):
        number = number.upper()
        if number in seen_titles:
            return True
        chapter_range = parse_chapter_range(raw_range)
        if chapter_range is None:
            unparsed.append(source_line)
            return False
        seen_titles.add(number)
        entry = {
            "titleNumber": number,
            "titleName": " ".join(name.split()),
            "volumeNumber": current_volume,
        }
        entry.update(chapter_range)
        titles.append(entry)
        return True

    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue

        volume_match = VOLUME_PATTERN.match(line)
        if volume_match is not None:
            if pending is not None:
                unresolved.append(pending["line"])
                pending = None
            current_volume = int(volume_match.group("number"))
            if all(item["volumeNumber"] != current_volume for item in volumes):
                volumes.append({"volumeNumber": current_volume})
            continue

        title_match = TITLE_PATTERN.match(line)
        if title_match is not None:
            if pending is not None:
                unresolved.append(pending["line"])
                pending = None
            record(
                title_match.group("number"),
                title_match.group("name"),
                title_match.group("range"),
                line,
            )
            continue

        if pending is not None:
            tail_match = TITLE_TAIL_PATTERN.match(line)
            if tail_match is not None:
                record(
                    pending["number"],
                    f'{pending["name"]} {tail_match.group("name")}',
                    tail_match.group("range"),
                    f'{pending["line"]} {line}',
                )
                pending = None
                continue
            unresolved.append(pending["line"])
            pending = None

        head_match = TITLE_HEAD_PATTERN.match(line)
        if head_match is not None:
            pending = {
                "number": head_match.group("number"),
                "name": head_match.group("name"),
                "line": line,
            }

    if pending is not None:
        unresolved.append(pending["line"])

    # Record each volume's chapter span from the titles it contains.
    for volume in volumes:
        owned = [item for item in titles if item["volumeNumber"] == volume["volumeNumber"]]
        if owned:
            volume["firstChapter"] = min(owned, key=lambda i: i["firstChapterSortKey"])["firstChapter"]
            volume["lastChapter"] = max(owned, key=lambda i: i["lastChapterSortKey"])["lastChapter"]
            volume["titleCount"] = len(owned)

    return volumes, titles, unparsed, unresolved


def chapter_is_published(chapter_number, titles):
    """Return the title covering a chapter number, or None.

    Containment compares sort keys, so a lettered chapter such as 90A falls
    correctly inside a printed range of 90-105.
    """
    key = chapter_sort_key(chapter_number)
    for title in titles:
        if title["firstChapterSortKey"] <= key <= title["lastChapterSortKey"]:
            return title
    return None


def text_diagnostics(text):
    lines = [" ".join(raw.split()) for raw in text.splitlines()]
    lines = [line for line in lines if line]
    return {
        "lineCount": len(lines),
        "charCount": len(text),
        "sampleLines": [line[:MAX_SAMPLE_LINE_CHARS] for line in lines[:MAX_SAMPLE_LINES]],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster-url", default=DEFAULT_ROSTER_URL)
    parser.add_argument("--pdf-file", help="use a local PDF instead of downloading one")
    parser.add_argument("--output", help="where to write the downloaded roster PDF")
    parser.add_argument("--tika-jar", required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--report", required=True)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)

    report = {
        "schemaVersion": 1,
        "stage": "roster",
        "rosterUrl": args.roster_url,
        "retrievedAt": utc_now(),
    }

    if args.pdf_file:
        pdf_path = Path(args.pdf_file)
        data = pdf_path.read_bytes()
        report["rosterSource"] = "file"
    else:
        data, status, attempts, error = fetch_bytes(args.roster_url, args.retries, args.timeout)
        report.update({
            "rosterSource": "network",
            "rosterHttpStatus": status,
            "rosterAttempts": attempts,
        })
        if data is None:
            report.update({"valid": False, "error": error, "titles": [], "volumes": []})
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"valid": False, "error": error}, indent=2))
            return 1
        if not args.output:
            parser.error("--output is required unless --pdf-file is given")
        pdf_path = Path(args.output)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(data)

    report.update({
        "rosterSha256": hashlib.sha256(data).hexdigest(),
        "rosterBytes": len(data),
        "rosterPath": str(pdf_path),
    })

    if not data.startswith(b"%PDF"):
        report.update({
            "valid": False,
            "error": "roster document is not a PDF",
            "titles": [],
            "volumes": [],
        })
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": report["error"]}, indent=2))
        return 1

    try:
        text = extract_text(pdf_path, args.tika_jar, args.java)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        report.update({"valid": False, "error": str(exc), "titles": [], "volumes": []})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1

    volumes, titles, unparsed, unresolved = parse_table_of_titles(text)
    edition_year = detect_edition_year(text)

    problems = []
    if not titles:
        problems.append("no titles parsed from the published table of titles")
    if not volumes:
        problems.append("no volumes parsed from the published table of titles")

    report.update({
        # The table of titles carries no edition banner. Edition identity is
        # established from the chapter documents, which print it, before any
        # row is emitted. See SCHEMA.md.
        "editionYear": edition_year,
        "editionId": str(edition_year) if edition_year else None,
        "volumeCount": len(volumes),
        "titleCount": len(titles),
        "unparsedLineCount": len(unparsed),
        # A number-led line that never became a title. This is the diagnostic
        # that makes a silently dropped title visible.
        "unresolvedTitleLineCount": len(unresolved),
        "volumes": volumes,
        "titles": titles,
        "unparsedLines": unparsed[:MAX_SAMPLE_LINES],
        "unresolvedTitleLines": unresolved[:MAX_SAMPLE_LINES],
        # This document does not enumerate chapters, so no chapter roster is
        # claimed. Chapters are validated against the title ranges instead.
        "chapterRosterAvailable": False,
        "valid": not problems,
    })
    if problems:
        report.update({
            "problems": problems,
            "error": "; ".join(problems),
            "textDiagnostics": text_diagnostics(text),
        })

    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    summary = {
        "valid": report["valid"],
        "editionYear": edition_year,
        "volumeCount": len(volumes),
        "titleCount": len(titles),
        "unparsedLineCount": len(unparsed),
        "unresolvedTitleLineCount": len(unresolved),
    }
    if problems:
        summary["problems"] = problems
        summary["textDiagnostics"] = report["textDiagnostics"]
    print(json.dumps(summary, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
