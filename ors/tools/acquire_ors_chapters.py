#!/usr/bin/env python3
"""Discover and acquire Oregon Revised Statutes chapter sources.

Stage 1 and 2 of the ORS relational-table pipeline. Discovery reads the
official ORS index page and extracts the chapter roster it publishes.
Acquisition downloads each chapter and pins its exact URL, SHA-256 digest and
byte count so every later parsing decision is traceable to reviewed bytes.

The tool never synthesizes a chapter roster from a guessed numeric range. If
the index cannot be read, that is reported as a structured failure rather than
papered over with an assumed chapter list.
"""
import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_INDEX_URL = "https://www.oregonlegislature.gov/bills_laws/pages/ors.aspx"
CHAPTER_URL_TEMPLATE = "https://www.oregonlegislature.gov/bills_laws/ors/ors{chapter_file}.html"
USER_AGENT = "oregon-law-parser-ors-table/1"

# Chapter documents are published as ors<NNN>[<letter>].html, for example
# ors001.html and ors279A.html. The letter suffix is part of the chapter
# number, not a version marker, so it is preserved. The directory segment is
# deliberately not required: the roster is identified by the document filename
# so a reorganized path does not silently yield an empty roster.
CHAPTER_HREF_PATTERN = re.compile(
    r"""(?:^|/)ors_?(?P<digits>\d{1,3})(?P<letter>[A-Za-z]?)\.html?$""",
    re.IGNORECASE,
)
HREF_PATTERN = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
CHAPTER_ARGUMENT_PATTERN = re.compile(r"^(?P<digits>\d{1,3})(?P<letter>[A-Za-z]?)$")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_chapter_number(digits, letter):
    """Return the chapter number as printed: no leading zeros, upper-case suffix."""
    return f"{int(digits)}{letter.upper()}"


def chapter_sort_key(chapter_number):
    """Order chapters the way the statute book does: 1 < 36A < 97 < 279A < 279B."""
    match = CHAPTER_ARGUMENT_PATTERN.match(chapter_number)
    if match is None:
        # Unparseable chapter numbers sort last rather than raising, so one
        # malformed index entry cannot abort a whole-edition acquisition.
        return "999999~"
    return f"{int(match.group('digits')):06d}{(match.group('letter') or ' ').upper()}"


def chapter_file_stem(chapter_number):
    """Map a chapter number back to its published file stem, e.g. 279A -> 279A."""
    match = CHAPTER_ARGUMENT_PATTERN.match(chapter_number)
    if match is None:
        raise ValueError(f"invalid chapter number: {chapter_number}")
    return f"{int(match.group('digits')):03d}{(match.group('letter') or '').upper()}"


def chapter_url(chapter_number):
    return CHAPTER_URL_TEMPLATE.format(chapter_file=chapter_file_stem(chapter_number))


def parse_chapter_index(index_html, index_url):
    """Extract the chapter roster from the official ORS index page.

    Returns chapters sorted in statute-book order. Duplicate links to the same
    chapter collapse to one entry, keeping the first URL seen so the roster is
    stable across runs.
    """
    seen = {}
    for raw_href in HREF_PATTERN.findall(index_html):
        href = html.unescape(raw_href).strip()
        match = CHAPTER_HREF_PATTERN.search(urllib.parse.urlsplit(href).path)
        if match is None:
            continue
        number = normalize_chapter_number(match.group("digits"), match.group("letter"))
        if number in seen:
            continue
        seen[number] = {
            "chapterNumber": number,
            "chapterSortKey": chapter_sort_key(number),
            "sourceUrl": urllib.parse.urljoin(index_url, href),
            "discoveredHref": href,
        }
    return sorted(seen.values(), key=lambda item: item["chapterSortKey"])


def index_diagnostics(index_html):
    """Describe an index page that produced no chapter roster.

    An empty roster is not self-explanatory: the page may have moved, been
    replaced by a redirect notice, or be rendering its links from script. This
    records enough of what was actually served to tell those cases apart,
    without dumping the page.
    """
    title = re.search(r"<title[^>]*>(.*?)</title>", index_html, re.IGNORECASE | re.DOTALL)
    hrefs = [html.unescape(href).strip() for href in HREF_PATTERN.findall(index_html)]
    prefixes = Counter()
    for href in hrefs:
        path = urllib.parse.urlsplit(href).path
        segments = [segment for segment in path.split("/") if segment]
        prefixes["/".join(segments[:2]) or "(root)"] += 1
    # Sample per prefix rather than alphabetically. A single sorted sample is
    # dominated by whichever prefix sorts first, which is how a page carrying
    # 115 links under one prefix produced a sample showing none of them.
    by_prefix = {}
    extensions_by_prefix = {}
    for href in hrefs:
        path = urllib.parse.urlsplit(href).path
        segments = [segment for segment in path.split("/") if segment]
        prefix = "/".join(segments[:2]) or "(root)"
        bucket = by_prefix.setdefault(prefix, [])
        if href not in bucket and len(bucket) < 12:
            bucket.append(href)
        basename = segments[-1] if segments else ""
        extension = basename.rsplit(".", 1)[-1].lower() if "." in basename else "(none)"
        extensions_by_prefix.setdefault(prefix, Counter())[extension] += 1

    # The largest prefix is where a chapter roster would live if the page
    # published one. A twelve-item sample cannot settle whether it does, so
    # every distinct basename under that prefix is listed. They are short, and
    # this is the question a discovery failure has to answer.
    top_prefix = prefixes.most_common(1)[0][0] if prefixes else None
    top_basenames = []
    if top_prefix is not None:
        seen = set()
        for href in hrefs:
            path = urllib.parse.urlsplit(href).path
            segments = [segment for segment in path.split("/") if segment]
            if ("/".join(segments[:2]) or "(root)") != top_prefix:
                continue
            basename = segments[-1] if segments else ""
            if basename and basename not in seen:
                seen.add(basename)
                top_basenames.append(basename)

    return {
        "pageTitle": " ".join(title.group(1).split()) if title else None,
        "topPrefix": top_prefix,
        "topPrefixBasenames": sorted(top_basenames)[:250],
        "anchorCount": len(re.findall(r"<\s*a\b", index_html, re.IGNORECASE)),
        "scriptCount": len(re.findall(r"<\s*script\b", index_html, re.IGNORECASE)),
        "hrefCount": len(hrefs),
        "hrefPathPrefixHistogram": [
            {
                "prefix": prefix,
                "count": count,
                "extensions": [
                    {"extension": extension, "count": extension_count}
                    for extension, extension_count
                    in extensions_by_prefix[prefix].most_common(6)
                ],
                "samples": by_prefix[prefix],
            }
            for prefix, count in prefixes.most_common(12)
        ],
    }


def detect_edition_year(index_html):
    """Read the edition year the index page advertises.

    Returns None when the page does not state one. A missing year is reported
    rather than guessed from the current date, because an edition published in
    one year is routinely browsed in the next.
    """
    matches = re.findall(r"((?:19|20)\d{2})\s+Edition", index_html)
    matches += re.findall(
        r"(?:Oregon Revised Statutes|ORS)[^0-9<]{0,40}((?:19|20)\d{2})", index_html
    )
    years = [int(match) for match in matches if 1953 <= int(match) <= 2100]
    if not years:
        return None
    return max(years)


def fetch_bytes(url, retries, timeout, context):
    """Fetch a URL with bounded exponential backoff.

    Returns (data, http_status, attempts, error). On success error is None; on
    failure data is None. Transient network faults are retried because a
    whole-edition acquisition makes several hundred requests.
    """
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
            # A 404 is an answer, not a transient fault. Stop retrying it.
            if exc.code == 404:
                return None, status, attempt, last_error
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{url}: {exc}"
        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 8))
    return None, status, retries, last_error or "unknown download error"


def source_format(url, data):
    if data.startswith(b"%PDF"):
        return "pdf"
    prefix = data[:4096].lower()
    if b"<html" in prefix or b"<!doctype html" in prefix:
        return "html"
    if url.lower().endswith((".html", ".htm")):
        return "html"
    return None


def fetch_chapter(chapter, output_dir, retries, timeout):
    url = chapter["sourceUrl"]
    context = ssl.create_default_context()
    data, status, attempts, error = fetch_bytes(url, retries, timeout, context)
    record = {
        "chapterNumber": chapter["chapterNumber"],
        "chapterSortKey": chapter["chapterSortKey"],
        "sourceUrl": url,
        "attempts": attempts,
        "httpStatus": status,
        "retrievedAt": utc_now(),
    }
    if data is None:
        record.update({"ok": False, "error": error})
        return record
    fmt = source_format(url, data)
    if fmt is None:
        record.update({"ok": False, "error": f"unsupported source format: {url}"})
        return record
    path = output_dir / f"ors{chapter_file_stem(chapter['chapterNumber'])}.{fmt}"
    path.write_bytes(data)
    record.update({
        "ok": True,
        "sourceFormat": fmt,
        "fixture": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    })
    return record


def read_chapter_selection_file(path):
    """Read a fixed chapter roster, such as the development sample manifest.

    The file names chapters to acquire; it does not describe them. Chapter
    identity still comes from the published index, so a sample entry that the
    edition no longer publishes surfaces as an error rather than being skipped.
    """
    document = json.loads(Path(path).read_text())
    entries = document.get("chapters")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"chapter selection file lists no chapters: {path}")
    numbers = []
    for entry in entries:
        number = entry.get("chapterNumber") if isinstance(entry, dict) else entry
        if not isinstance(number, str) or not number.strip():
            raise ValueError(f"chapter selection file has a malformed entry: {entry!r}")
        numbers.append(number.strip())
    return numbers


def selected_chapters(chapters, requested, limit):
    if requested:
        wanted = []
        for raw in requested:
            match = CHAPTER_ARGUMENT_PATTERN.match(raw.strip())
            if match is None:
                raise ValueError(f"invalid --chapters entry: {raw}")
            wanted.append(normalize_chapter_number(match.group("digits"), match.group("letter")))
        by_number = {item["chapterNumber"]: item for item in chapters}
        missing = [number for number in wanted if number not in by_number]
        if missing:
            raise ValueError(f"chapters not present in the published index: {', '.join(missing)}")
        chosen = [by_number[number] for number in wanted]
    else:
        chosen = list(chapters)
    if limit is not None:
        chosen = chosen[:limit]
    return sorted(chosen, key=lambda item: item["chapterSortKey"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--index-file", help="read the index page from disk instead of the network")
    parser.add_argument("--index-only", action="store_true", help="discover chapters, download none")
    parser.add_argument(
        "--without-index",
        action="store_true",
        help=(
            "skip the index page and build URLs from the chapters named on the command "
            "line. Naming a chapter explicitly is not the same as synthesizing a roster: "
            "the run is marked rosterVerified false and must not be treated as complete."
        ),
    )
    parser.add_argument("--chapters", help="comma-separated chapter numbers, e.g. 1,161,279A")
    parser.add_argument(
        "--chapters-file",
        help="JSON file naming the chapters to acquire, e.g. ors/sample/chapters.json",
    )
    parser.add_argument("--limit", type=int, help="acquire at most this many chapters")
    parser.add_argument("--output-dir")
    parser.add_argument("--report", required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)

    if args.chapters and args.chapters_file:
        parser.error("--chapters and --chapters-file are mutually exclusive")
    if args.without_index:
        if args.index_only:
            parser.error("--without-index and --index-only are mutually exclusive")
        if not (args.chapters or args.chapters_file):
            parser.error("--without-index requires --chapters or --chapters-file")
    if not args.index_only and not args.output_dir:
        parser.error("--output-dir is required unless --index-only is given")
    if not 1 <= args.workers <= 16:
        parser.error("workers must be between 1 and 16")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be a positive integer")

    report = {
        "schemaVersion": 1,
        "stage": "index" if args.index_only else "acquire",
        "indexUrl": args.index_url,
        "retrievedAt": utc_now(),
    }

    if args.without_index:
        try:
            if args.chapters_file:
                requested = read_chapter_selection_file(args.chapters_file)
            else:
                requested = [part for part in args.chapters.split(",") if part.strip()]
            chapters = []
            for raw in requested:
                match = CHAPTER_ARGUMENT_PATTERN.match(raw.strip())
                if match is None:
                    raise ValueError(f"invalid chapter number: {raw}")
                number = normalize_chapter_number(match.group("digits"), match.group("letter"))
                chapters.append({
                    "chapterNumber": number,
                    "chapterSortKey": chapter_sort_key(number),
                    "sourceUrl": chapter_url(number),
                })
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            report.update({"valid": False, "error": str(exc), "chapters": []})
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
            return 1
        report.update({
            "indexSource": "skipped",
            "rosterVerified": False,
            "editionYear": None,
            "editionId": None,
            "discoveredChapterCount": None,
        })
        return acquire_chapters(args, report, sorted(chapters, key=lambda c: c["chapterSortKey"]))

    if args.index_file:
        index_bytes = Path(args.index_file).read_bytes()
        report["indexSource"] = "file"
    else:
        context = ssl.create_default_context()
        index_bytes, status, attempts, error = fetch_bytes(
            args.index_url, args.retries, args.timeout, context
        )
        report["indexSource"] = "network"
        report["indexHttpStatus"] = status
        report["indexAttempts"] = attempts
        if index_bytes is None:
            report.update({"valid": False, "error": error, "chapters": []})
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"valid": False, "error": error}, indent=2))
            return 1

    index_html = index_bytes.decode("utf-8", errors="replace")
    chapters = parse_chapter_index(index_html, args.index_url)
    edition_year = detect_edition_year(index_html)

    report.update({
        "indexSha256": hashlib.sha256(index_bytes).hexdigest(),
        "indexBytes": len(index_bytes),
        "editionYear": edition_year,
        "editionId": str(edition_year) if edition_year else None,
        "discoveredChapterCount": len(chapters),
    })

    # Both problems are collected before returning so one run reports
    # everything wrong with the index rather than only the first fault.
    problems = []
    if not chapters:
        problems.append("no chapter links matched the published index page")
    if edition_year is None:
        # editionId is the primary key of ors_edition and the discriminator
        # between editions in every other table. Discovering chapters without
        # it would produce rows that cannot be filed against an edition, so a
        # missing edition year is a failure, not a nullable field.
        problems.append("the index page states no ORS edition year")

    if problems:
        diagnostics = index_diagnostics(index_html)
        report.update({
            "valid": False,
            "error": "; ".join(problems),
            "problems": problems,
            "indexDiagnostics": diagnostics,
            "chapters": chapters,
        })
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({
            "valid": False,
            "problems": problems,
            "indexHttpStatus": report.get("indexHttpStatus"),
            "indexBytes": report["indexBytes"],
            "discoveredChapterCount": len(chapters),
            "indexDiagnostics": diagnostics,
        }, indent=2))
        return 1

    if args.index_only:
        report.update({"valid": True, "chapters": chapters})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({
            "valid": True,
            "editionYear": edition_year,
            "discoveredChapterCount": len(chapters),
            "firstChapter": chapters[0]["chapterNumber"],
            "lastChapter": chapters[-1]["chapterNumber"],
        }, indent=2))
        return 0

    try:
        if args.chapters_file:
            requested = read_chapter_selection_file(args.chapters_file)
        else:
            requested = [part for part in (args.chapters or "").split(",") if part.strip()]
        chosen = selected_chapters(chapters, requested, args.limit)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report.update({"valid": False, "error": str(exc), "chapters": []})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1

    report["rosterVerified"] = True
    return acquire_chapters(args, report, chosen)


def acquire_chapters(args, report, chosen):
    """Download the chosen chapters and finish the acquisition report."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(fetch_chapter, chapter, output_dir, args.retries, args.timeout)
            for chapter in chosen
        ]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(f'ORS chapter {result["chapterNumber"]}: {"ok" if result["ok"] else "FAILED"}', flush=True)

    results.sort(key=lambda item: item["chapterSortKey"])
    failures = [item for item in results if not item["ok"]]
    report.update({
        "chapterSelectionSource": args.chapters_file or ("--chapters" if args.chapters else "whole-edition"),
        "chapterUrlSource": "index" if report.get("rosterVerified") else "constructed",
        "requestedChapterCount": len(chosen),
        "acquiredChapterCount": sum(1 for item in results if item["ok"]),
        "valid": not failures and len(results) == len(chosen),
        "chapters": results,
        "failures": failures,
    })
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "valid": report["valid"],
        "rosterVerified": report.get("rosterVerified", False),
        "editionYear": report.get("editionYear"),
        "discoveredChapterCount": report.get("discoveredChapterCount"),
        "requestedChapterCount": len(chosen),
        "acquiredChapterCount": report["acquiredChapterCount"],
        "failureCount": len(failures),
    }, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
