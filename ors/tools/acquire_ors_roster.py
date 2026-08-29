#!/usr/bin/env python3
"""Discover the ORS title and chapter roster from the published roster document.

The ORS landing page does not link chapters. Its 115 links under
bills_laws/ors are the annual amendment-and-repeal reference PDFs (1941
through 2025, special sessions included), OCLA.pdf, and the alphabetical
General Index. The authoritative roster is published separately as
ORS_TitlesChapters.pdf.

Reading it is better than scraping links would have been: it carries title
grouping and chapter names, so it populates ors_title and
ors_chapter.chapter_name directly instead of leaving them to be recovered
from each chapter document.

Text is extracted with the Tika jar already vendored for the amendment
parser. Parsing never guesses: lines that look like roster entries but do not
parse are reported, and a run that finds no chapters fails with a text
fingerprint attached rather than returning an empty roster.
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

# "TITLE 1" or "Title 1." introduces a title, whose name may follow on the
# same line or on the next one.
TITLE_PATTERN = re.compile(r"^TITLE\s+(?P<number>[0-9]{1,3}[A-Z]?)\b\.?\s*(?P<name>.*)$", re.IGNORECASE)
# A chapter entry is a chapter number followed by its name. The roster prints
# these either bare ("1 Courts and Judicial Districts") or with a "Chapter"
# label, so both are accepted.
CHAPTER_PATTERN = re.compile(
    r"^(?:Chapter\s+)?(?P<number>[0-9]{1,3}[A-Z]?)[.,]?\s+(?P<name>\S.*)$",
    re.IGNORECASE,
)
# A line that is only a number is a page number, not a chapter.
PAGE_NUMBER_PATTERN = re.compile(r"^[0-9ivxlcIVXLC]{1,6}$")
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


def parse_roster(text):
    """Parse titles and chapters out of the extracted roster text.

    Returns (titles, chapters, unparsed_lines). A line naming a chapter number
    that cannot be normalized is reported rather than dropped, so a layout
    this parser does not understand is visible instead of silently shrinking
    the roster.
    """
    titles = []
    chapters = []
    unparsed = []
    seen_chapters = set()
    seen_titles = set()
    current_title = None

    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line or PAGE_NUMBER_PATTERN.match(line):
            continue

        title_match = TITLE_PATTERN.match(line)
        if title_match is not None:
            number = title_match.group("number").upper()
            current_title = number
            if number not in seen_titles:
                seen_titles.add(number)
                titles.append({
                    "titleNumber": number,
                    "titleName": title_match.group("name").strip() or None,
                })
            continue

        chapter_match = CHAPTER_PATTERN.match(line)
        if chapter_match is None:
            continue
        number = parse_chapter_number(chapter_match.group("number"))
        if number is None:
            unparsed.append(line)
            continue
        if number in seen_chapters:
            continue
        seen_chapters.add(number)
        chapters.append({
            "chapterNumber": number,
            "chapterSortKey": chapter_sort_key(number),
            "chapterName": chapter_match.group("name").strip(),
            "titleNumber": current_title,
            "sourceUrl": chapter_url(number),
        })

    chapters.sort(key=lambda item: item["chapterSortKey"])
    return titles, chapters, unparsed


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
            report.update({"valid": False, "error": error, "chapters": [], "titles": []})
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
            "chapters": [],
            "titles": [],
        })
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": report["error"]}, indent=2))
        return 1

    try:
        text = extract_text(pdf_path, args.tika_jar, args.java)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        report.update({"valid": False, "error": str(exc), "chapters": [], "titles": []})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1

    titles, chapters, unparsed = parse_roster(text)
    edition_year = detect_edition_year(text)

    problems = []
    if not chapters:
        problems.append("no chapters parsed from the published roster document")
    if edition_year is None:
        problems.append("the roster document states no ORS edition year")

    report.update({
        "editionYear": edition_year,
        "editionId": str(edition_year) if edition_year else None,
        "titleCount": len(titles),
        "chapterCount": len(chapters),
        "unparsedLineCount": len(unparsed),
        "titles": titles,
        "chapters": chapters,
        "unparsedLines": unparsed[:MAX_SAMPLE_LINES],
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
        "titleCount": len(titles),
        "chapterCount": len(chapters),
        "unparsedLineCount": len(unparsed),
    }
    if problems:
        summary["problems"] = problems
        summary["textDiagnostics"] = report["textDiagnostics"]
    print(json.dumps(summary, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
