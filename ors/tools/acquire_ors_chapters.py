#!/usr/bin/env python3
"""Acquire ORS chapter documents.

No published document enumerates ORS chapters. The landing page links only
reference PDFs, and ORS_TitlesChapters.pdf is a table of titles giving each
title's chapter RANGE rather than a chapter list. Chapters to acquire are
therefore named explicitly -- by the fixed development sample, or on the
command line -- and never synthesized from a guessed numeric span.

When the table of titles is supplied, every named chapter is checked against
the published ranges before anything is fetched, and the owning title and
volume travel with the acquired document. A chapter that falls under no
published title is a failure, not a silent acquisition: it means either the
name is wrong or the edition's structure has changed.

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


def read_title_roster(path):
    """Read the table of titles produced by acquire_ors_roster.py."""
    document = json.loads(Path(path).read_text())
    titles = document.get("titles")
    if not isinstance(titles, list) or not titles:
        raise ValueError(f"title roster names no titles: {path}")
    for title in titles:
        for field in ("firstChapterSortKey", "lastChapterSortKey", "titleNumber"):
            if field not in title:
                raise ValueError(f"title roster entry is missing {field}: {title!r}")
    return document, titles


def covering_title(chapter_number, titles):
    """Return the published title covering a chapter number, or None."""
    key = chapter_sort_key(chapter_number)
    for title in titles:
        if title["firstChapterSortKey"] <= key <= title["lastChapterSortKey"]:
            return title
    return None


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


def chapter_entries(requested, titles, template, limit):
    """Build chapter entries for the explicitly requested chapters.

    When a table of titles is supplied, a chapter outside every published
    range is rejected rather than fetched.
    """
    entries = []
    outside = []
    for raw in requested:
        number = parse_chapter_number(raw)
        if number is None:
            raise ValueError(f"invalid chapter number: {raw}")
        title = covering_title(number, titles) if titles else None
        if titles and title is None:
            outside.append(number)
            continue
        entries.append({
            "chapterNumber": number,
            "chapterSortKey": chapter_sort_key(number),
            "titleNumber": title["titleNumber"] if title else None,
            "titleName": title.get("titleName") if title else None,
            "volumeNumber": title.get("volumeNumber") if title else None,
            "sourceUrl": chapter_url(number, template),
        })
    if outside:
        raise ValueError(
            "chapters fall outside every published title range: " + ", ".join(outside)
        )
    entries.sort(key=lambda item: item["chapterSortKey"])
    if limit is not None:
        entries = entries[:limit]
    return entries


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
        "titleNumber": chapter.get("titleNumber"),
        "titleName": chapter.get("titleName"),
        "volumeNumber": chapter.get("volumeNumber"),
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
        "chapterSelectionSource": args.chapters_file or "--chapters",
        "requestedChapterCount": len(chosen),
        "acquiredChapterCount": sum(1 for item in results if item["ok"]),
        "valid": not failures and len(results) == len(chosen),
        "chapters": results,
        "failures": failures,
    })
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "valid": report["valid"],
        "titleRangesChecked": report.get("titleRangesChecked", False),
        "titleRosterCount": report.get("titleRosterCount"),
        "requestedChapterCount": len(chosen),
        "acquiredChapterCount": report["acquiredChapterCount"],
        "failureCount": len(failures),
    }, indent=2))
    return 0 if report["valid"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--title-roster-file",
        help=(
            "table of titles from acquire_ors_roster.py. When given, every "
            "requested chapter must fall inside a published title range."
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
    if not (args.chapters or args.chapters_file):
        parser.error("one of --chapters or --chapters-file is required")
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
        else:
            requested = [part for part in args.chapters.split(",") if part.strip()]

        titles = []
        if args.title_roster_file:
            roster_document, titles = read_title_roster(args.title_roster_file)
            report.update({
                "titleRosterSource": args.title_roster_file,
                "titleRosterUrl": roster_document.get("rosterUrl"),
                "titleRosterSha256": roster_document.get("rosterSha256"),
                "titleRosterCount": len(titles),
                "titleRangesChecked": True,
            })
        else:
            # Acquiring without the published ranges is allowed for isolating a
            # failure, but the report must never imply the chapters were checked.
            report.update({
                "titleRosterSource": None,
                "titleRosterCount": None,
                "titleRangesChecked": False,
            })

        chosen = chapter_entries(requested, titles, args.url_template, args.limit)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report.update({"valid": False, "error": str(exc), "chapters": []})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1

    return acquire_chapters(args, report, chosen)


if __name__ == "__main__":
    sys.exit(main())
