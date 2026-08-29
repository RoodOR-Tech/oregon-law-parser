#!/usr/bin/env python3
"""Acquire ORS chapter documents named by a published roster.

Chapter identity comes from the roster produced by acquire_ors_roster.py,
which reads the authoritative ORS_TitlesChapters.pdf. This tool does not
discover chapters itself and never synthesizes a roster from a numeric range:
a chapter the edition does not publish must surface as a failure, not as a
gap nobody notices.

Every fetch pins its exact URL, SHA-256 digest and byte count so any later
parsing decision is traceable to reviewed bytes.
"""
import argparse
import concurrent.futures
import hashlib
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ors_chapters import (  # noqa: E402
    CHAPTER_URL_TEMPLATE,
    chapter_file_stem,
    chapter_sort_key,
    chapter_url,
    parse_chapter_number,
)

USER_AGENT = "oregon-law-parser-ors-table/1"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_roster(path):
    """Read the chapter roster produced by acquire_ors_roster.py."""
    document = json.loads(Path(path).read_text())
    chapters = document.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise ValueError(f"roster file names no chapters: {path}")
    roster = []
    for entry in chapters:
        number = parse_chapter_number(str(entry.get("chapterNumber", "")))
        if number is None:
            raise ValueError(f"roster has a malformed chapter number: {entry!r}")
        roster.append({
            "chapterNumber": number,
            "chapterSortKey": chapter_sort_key(number),
            "chapterName": entry.get("chapterName"),
            "titleNumber": entry.get("titleNumber"),
            "sourceUrl": entry.get("sourceUrl") or chapter_url(number),
        })
    return document, sorted(roster, key=lambda item: item["chapterSortKey"])


def read_chapter_selection_file(path):
    """Read a fixed list of chapter numbers, such as the development sample."""
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


def selected_chapters(roster, requested, limit):
    """Restrict the roster to the requested chapters, in statute-book order."""
    if requested:
        wanted = []
        for raw in requested:
            number = parse_chapter_number(raw)
            if number is None:
                raise ValueError(f"invalid chapter number: {raw}")
            wanted.append(number)
        by_number = {item["chapterNumber"]: item for item in roster}
        missing = [number for number in wanted if number not in by_number]
        if missing:
            raise ValueError(
                f"chapters not present in the published roster: {', '.join(missing)}"
            )
        chosen = [by_number[number] for number in wanted]
    else:
        chosen = list(roster)
    if limit is not None:
        chosen = chosen[:limit]
    return sorted(chosen, key=lambda item: item["chapterSortKey"])


def constructed_chapters(requested, template=None):
    """Build chapter entries for explicitly named chapters, with no roster.

    Naming a chapter is not the same as synthesizing a roster. A run built
    this way is recorded as rosterVerified false so it can never be mistaken
    for a complete edition.
    """
    entries = []
    for raw in requested:
        number = parse_chapter_number(raw)
        if number is None:
            raise ValueError(f"invalid chapter number: {raw}")
        entries.append({
            "chapterNumber": number,
            "chapterSortKey": chapter_sort_key(number),
            "chapterName": None,
            "titleNumber": None,
            "sourceUrl": chapter_url(number, template),
        })
    return sorted(entries, key=lambda item: item["chapterSortKey"])


def fetch_bytes(url, retries, timeout, context):
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
        "chapterName": chapter.get("chapterName"),
        "titleNumber": chapter.get("titleNumber"),
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
            status = "ok" if result["ok"] else "FAILED"
            print(f'ORS chapter {result["chapterNumber"]}: {status}', flush=True)

    results.sort(key=lambda item: item["chapterSortKey"])
    failures = [item for item in results if not item["ok"]]
    report.update({
        "chapterSelectionSource": (
            args.chapters_file or ("--chapters" if args.chapters else "whole-roster")
        ),
        "chapterUrlSource": "roster" if report.get("rosterVerified") else "constructed",
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
        "rosterChapterCount": report.get("rosterChapterCount"),
        "requestedChapterCount": len(chosen),
        "acquiredChapterCount": report["acquiredChapterCount"],
        "failureCount": len(failures),
    }, indent=2))
    return 0 if report["valid"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster-file", help="roster JSON from acquire_ors_roster.py")
    parser.add_argument(
        "--without-roster",
        action="store_true",
        help=(
            "build URLs from the chapters named on the command line, with no roster. "
            "Such a run is marked rosterVerified false and must not be treated as "
            "a complete edition."
        ),
    )
    parser.add_argument("--chapters", help="comma-separated chapter numbers, e.g. 1,161,279A")
    parser.add_argument(
        "--chapters-file",
        help="JSON file naming the chapters to acquire, e.g. ors/sample/chapters.json",
    )
    parser.add_argument("--limit", type=int, help="acquire at most this many chapters")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--url-template", default=CHAPTER_URL_TEMPLATE)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)

    if args.chapters and args.chapters_file:
        parser.error("--chapters and --chapters-file are mutually exclusive")
    if args.roster_file and args.without_roster:
        parser.error("--roster-file and --without-roster are mutually exclusive")
    if not args.roster_file and not args.without_roster:
        parser.error("one of --roster-file or --without-roster is required")
    if args.without_roster and not (args.chapters or args.chapters_file):
        parser.error("--without-roster requires --chapters or --chapters-file")
    if not 1 <= args.workers <= 16:
        parser.error("workers must be between 1 and 16")
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be a positive integer")

    report = {
        "schemaVersion": 1,
        "stage": "acquire",
        "retrievedAt": utc_now(),
    }

    try:
        if args.chapters_file:
            requested = read_chapter_selection_file(args.chapters_file)
        elif args.chapters:
            requested = [part for part in args.chapters.split(",") if part.strip()]
        else:
            requested = []

        if args.without_roster:
            report.update({
                "rosterSource": "skipped",
                "rosterVerified": False,
                "editionYear": None,
                "editionId": None,
                "rosterChapterCount": None,
            })
            chosen = constructed_chapters(requested, args.url_template)
            if args.limit is not None:
                chosen = chosen[: args.limit]
        else:
            roster_document, roster = read_roster(args.roster_file)
            report.update({
                "rosterSource": args.roster_file,
                "rosterVerified": True,
                "rosterUrl": roster_document.get("rosterUrl"),
                "rosterSha256": roster_document.get("rosterSha256"),
                "editionYear": roster_document.get("editionYear"),
                "editionId": roster_document.get("editionId"),
                "rosterChapterCount": len(roster),
            })
            chosen = selected_chapters(roster, requested, args.limit)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report.update({"valid": False, "error": str(exc), "chapters": []})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1

    return acquire_chapters(args, report, chosen)


if __name__ == "__main__":
    sys.exit(main())
