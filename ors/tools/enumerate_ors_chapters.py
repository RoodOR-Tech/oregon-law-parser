#!/usr/bin/env python3
"""Enumerate ORS chapters by verified probing, not by guessing a numeric span.

No published document lists ORS chapters directly. ORS_TitlesChapters.pdf
gives each title a chapter RANGE ("Chs. 284-285C"), not a chapter list, and
the range alone answers neither of the two questions a whole-edition build
needs: which integers inside that span are real chapters (some are gaps --
chapter 11 sits between titles 1 and 2 and does not exist), and how far a
lettered family actually runs (does 285 stop at 285A, 285B or 285C?). This
tool answers both by fetching every candidate document and recording what
the server actually says, rather than assuming the printed endpoints are the
whole story.

For each integer inside a title's own declared range (never beyond it, so
the gap between two titles is never even probed):

- the bare chapter (e.g. 90) is always probed: a 200 is a real chapter, a
  404 is a confirmed gap.
- lettered siblings (90A, 90B, ...) are then probed in order starting from
  A, regardless of whether the bare number itself existed -- verification
  rather than guessing means not assuming a lettered sibling can only exist
  alongside its bare number. The walk for that digit stops at the first
  probe that is not a confirmed chapter, since Oregon letters a family
  without gaps: once a letter is missing, nothing past it needs trying.

Every probe made -- chapter, confirmed absence, or an inconclusive failure
(timeout, 5xx) -- is recorded, so a reviewer can see the gap was checked
rather than assumed. A failure is neither a chapter nor a verified absence
and is reported under its own count rather than folded into either.

The report this tool writes uses the same per-chapter shape as
acquire_ors_chapters.py's own acquisition report (chapterNumber, ok,
sourceFormat, fixture, sha256, bytes, titleNumber, ...), so it can be handed
directly to probe_ors_structure.py, parse_ors_chapter.py and
build_ors_relational.py as their --acquisition-report/--acquisition input --
a confirmed absence or failure simply carries ok: false and is filtered out
by their existing `chapter.get("ok")` checks, exactly like a chapter that
was requested explicitly but never fetched.

This is a whole-edition operation: walking every title's range costs on the
order of a thousand requests, so per ROADMAP.md's working method it runs on
manual dispatch rather than on every CI run.
"""
import argparse
import concurrent.futures
import hashlib
import json
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from acquire_ors_chapters import fetch_bytes, source_format  # noqa: E402
from ors_chapters import (  # noqa: E402
    CHAPTER_NUMBER_PATTERN,
    CHAPTER_URL_TEMPLATE,
    chapter_file_stem,
    chapter_sort_key,
    chapter_url,
)

# a-z: a family running past Z would be a real anomaly, not a real chapter
# range, so this is a safety cap rather than an expected stopping point.
MAX_LETTER_INDEX = 26


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_title_roster(path):
    """Read the table of titles produced by acquire_ors_roster.py."""
    document = json.loads(Path(path).read_text())
    titles = document.get("titles")
    if not isinstance(titles, list) or not titles:
        raise ValueError(f"title roster names no titles: {path}")
    for title in titles:
        for field in (
            "firstChapter", "lastChapter",
            "firstChapterSortKey", "lastChapterSortKey", "titleNumber",
        ):
            if field not in title:
                raise ValueError(f"title roster entry is missing {field}: {title!r}")
    return document, titles


def chapter_digits(chapter_number):
    match = CHAPTER_NUMBER_PATTERN.match(chapter_number)
    if match is None:
        raise ValueError(f"invalid chapter number: {chapter_number}")
    return int(match.group("digits"))


def select_titles(titles, wanted):
    if wanted is None:
        return titles
    wanted = {number.strip().upper() for number in wanted if number.strip()}
    selected = [title for title in titles if title["titleNumber"].upper() in wanted]
    missing = wanted - {title["titleNumber"].upper() for title in selected}
    if missing:
        raise ValueError("no such title in the roster: " + ", ".join(sorted(missing)))
    return selected


def candidate_digit_range(titles):
    """The integer chapter numbers to probe, from every title's own range.

    A range is walked only within its own declared endpoints, so a gap
    between two titles (chapter 11, between titles 1 and 2) is never probed
    at all -- it is already known to be outside every published title,
    exactly like acquire_ors_chapters.py's own rejection of such a chapter.
    """
    digits = set()
    for title in titles:
        first = chapter_digits(title["firstChapter"])
        last = chapter_digits(title["lastChapter"])
        digits.update(range(first, last + 1))
    return sorted(digits)


def covering_title(chapter_number, titles):
    """Return the published title covering a chapter number, or None."""
    key = chapter_sort_key(chapter_number)
    for title in titles:
        if title["firstChapterSortKey"] <= key <= title["lastChapterSortKey"]:
            return title
    return None


def probe_chapter(chapter_number, url_template, output_dir, retries, timeout, context):
    """Probe one candidate chapter, saving its bytes when the answer is 200.

    The record shape matches acquire_ors_chapters.py's own acquisition
    record (ok/httpStatus/attempts/sha256/bytes/fixture) plus an `outcome`
    tag (chapter/absent/failure) that acquisition itself has no use for,
    since every chapter it acquires is already believed to exist.
    """
    url = chapter_url(chapter_number, url_template)
    data, status, attempts, error = fetch_bytes(url, retries, timeout, context)
    record = {
        "chapterNumber": chapter_number,
        "chapterSortKey": chapter_sort_key(chapter_number),
        "sourceUrl": url,
        "attempts": attempts,
        "httpStatus": status,
        "retrievedAt": utc_now(),
    }
    if data is None:
        if status == 404:
            record.update({"outcome": "absent", "ok": False})
        else:
            record.update({"outcome": "failure", "ok": False, "error": error})
        return record
    fmt = source_format(url, data)
    if fmt is None:
        record.update({
            "outcome": "failure", "ok": False,
            "error": f"unsupported source format: {url}",
        })
        return record
    path = output_dir / f"ors{chapter_file_stem(chapter_number)}.{fmt}"
    path.write_bytes(data)
    record.update({
        "outcome": "chapter",
        "ok": True,
        "sourceFormat": fmt,
        "fixture": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    })
    return record


def probe_digit_family(digits, url_template, output_dir, retries, timeout, context):
    """Probe one integer and its lettered siblings, in declared-letter order.

    The bare number is always probed first. Letters are then probed starting
    from A regardless of the bare number's own outcome, and the walk for
    this digit stops the first time a probe is not a confirmed chapter --
    a confirmed absence and an inconclusive failure both end it, though only
    an absence is a verified answer; a failure is reported separately so it
    is investigated rather than treated as a gap.
    """
    records = [probe_chapter(str(digits), url_template, output_dir, retries, timeout, context)]
    for letter_index in range(MAX_LETTER_INDEX):
        letter = chr(ord("A") + letter_index)
        record = probe_chapter(
            f"{digits}{letter}", url_template, output_dir, retries, timeout, context
        )
        records.append(record)
        if record["outcome"] != "chapter":
            break
    else:
        records[-1]["letterCapReached"] = True
    return records


def enumerate_chapters(titles, url_template, output_dir, workers, retries, timeout):
    context = ssl.create_default_context()
    digit_list = candidate_digit_range(titles)
    all_records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                probe_digit_family, digits, url_template, output_dir, retries, timeout, context
            )
            for digits in digit_list
        ]
        for index, future in enumerate(futures):
            all_records.extend(future.result())
            print(
                f"ORS enumeration: {index + 1}/{len(futures)} chapter numbers probed",
                flush=True,
            )
    all_records.sort(key=lambda item: item["chapterSortKey"])
    for record in all_records:
        if record["outcome"] == "chapter":
            title = covering_title(record["chapterNumber"], titles)
            record["titleNumber"] = title["titleNumber"] if title else None
            record["titleName"] = title.get("titleName") if title else None
            record["volumeNumber"] = title.get("volumeNumber") if title else None
    return all_records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--title-roster-file", required=True,
        help="table of titles from acquire_ors_roster.py",
    )
    parser.add_argument(
        "--titles",
        help="comma-separated title numbers to enumerate, e.g. 1,16 (default: every title)",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--url-template", default=CHAPTER_URL_TEMPLATE)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)

    if not 1 <= args.workers <= 16:
        parser.error("workers must be between 1 and 16")

    report = {
        "schemaVersion": 1,
        "stage": "enumerate",
        "retrievedAt": utc_now(),
        "titleRosterSource": args.title_roster_file,
        # Every candidate this tool probes is checked against the roster's
        # own ranges by construction, so this is always true -- present for
        # a reader that treats this report interchangeably with an
        # acquisition report, which only claims it conditionally.
        "titleRangesChecked": True,
    }

    try:
        roster_document, titles = read_title_roster(args.title_roster_file)
        wanted = [part for part in args.titles.split(",")] if args.titles else None
        titles = select_titles(titles, wanted)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        report.update({"valid": False, "error": str(exc), "chapters": []})
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    records = enumerate_chapters(
        titles, args.url_template, output_dir, args.workers, args.retries, args.timeout
    )
    absences = [r for r in records if r["outcome"] == "absent"]
    failures = [r for r in records if r["outcome"] == "failure"]

    report.update({
        "titleRosterUrl": roster_document.get("rosterUrl"),
        "titleRosterSha256": roster_document.get("rosterSha256"),
        "titleRosterCount": len(titles),
        "probedCount": len(records),
        "chapterCount": sum(1 for r in records if r["outcome"] == "chapter"),
        "absenceCount": len(absences),
        "failureCount": len(failures),
        "valid": not failures,
        # Shaped like acquire_ors_chapters.py's own "chapters": every probe,
        # ok true only for a confirmed chapter, so a downstream reader that
        # filters on .get("ok") sees exactly the real chapters either way.
        "chapters": records,
        "absences": absences,
        "failures": failures,
    })
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "valid": report["valid"],
        "titleRosterCount": len(titles),
        "probedCount": len(records),
        "chapterCount": report["chapterCount"],
        "absenceCount": len(absences),
        "failureCount": len(failures),
    }, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
