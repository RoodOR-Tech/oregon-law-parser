#!/usr/bin/env python3
import argparse
import concurrent.futures
import hashlib
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MODERN_BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/{year}orlaw{chapter:04d}.pdf"
LEGACY_REGULAR_BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/{year}R1orLaw{chapter:04d}ss.pdf"
LEGACY_ADVANCE_BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/{year}adv{chapter:04d}ss.pdf"
LEGACY_HTML_BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/{year}orLaw{chapter:04d}.html"
LEGACY_2007_SESSION_HTML_BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2007R1{chapter:04d}.html"
LEGACY_2006_SPECIAL_BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/2006orLaw{chapter:04d}ss1.pdf"
USER_AGENT = "oregon-law-parser-session-scale/1"


def source_url_candidates(year, chapter):
    urls = [MODERN_BASE_URL.format(year=year, chapter=chapter)]
    # Oregon's older archive uses multiple regular-session source conventions.
    # Keep established PDF URLs first so existing session provenance remains stable.
    if year <= 2014:
        urls.append(LEGACY_REGULAR_BASE_URL.format(year=year, chapter=chapter))
    if year == 2012:
        urls.append(LEGACY_ADVANCE_BASE_URL.format(year=year, chapter=chapter))
    # The 2011 and older archive exposes enacted chapters as official HTML pages.
    # Preserve the exact successful URL and source bytes rather than synthesizing a PDF.
    if year <= 2011:
        urls.append(LEGACY_HTML_BASE_URL.format(year=year, chapter=chapter))
    # A subset of the 2007 regular-session archive uses the older session-prefixed
    # HTML naming convention (for example 2007R10070.html and 2007R10071.html).
    # Keep this as the final fallback so previously successful source provenance is stable.
    if year == 2007:
        urls.append(LEGACY_2007_SESSION_HTML_BASE_URL.format(chapter=chapter))
    # The 2006 special-session archive uses an ss1 suffix after the chapter number
    # (for example 2006orLaw0001ss1.pdf). Keep this year-specific fallback last so
    # all previously successful acquisition URLs and hashes remain unchanged.
    if year == 2006:
        urls.append(LEGACY_2006_SPECIAL_BASE_URL.format(chapter=chapter))
    return urls


def source_kind(url, data):
    if data.startswith(b"%PDF"):
        return "pdf"
    if url.lower().endswith(".html"):
        prefix = data[:4096].lower()
        if b"<html" in prefix or b"<!doctype html" in prefix:
            return "html"
    return None


def fetch_one(year, chapter, output_dir, retries, timeout):
    doc_id = f"{year}orlaw{chapter:04d}"
    urls = source_url_candidates(year, chapter)
    context = ssl.create_default_context()
    last_error = None
    attempted_urls = []
    for attempt in range(1, retries + 1):
        for url in urls:
            attempted_urls.append(url)
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
                    data = response.read()
                kind = source_kind(url, data)
                if kind is None:
                    last_error = f"downloaded source has unsupported format: {url}"
                    continue
                path = output_dir / f"{doc_id}.{kind}"
                digest = hashlib.sha256(data).hexdigest()
                path.write_bytes(data)
                return {
                    "id": doc_id,
                    "chapter": chapter,
                    "sourceUrl": url,
                    "sourceFormat": kind,
                    "fixture": str(path),
                    "ok": True,
                    "sha256": digest,
                    "bytes": len(data),
                    "attempts": attempt,
                    "sourceUrlsTried": attempted_urls,
                }
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"{url}: {exc}"
        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 8))
    return {
        "id": doc_id,
        "chapter": chapter,
        "sourceUrl": urls[0],
        "sourceUrlsTried": attempted_urls,
        "ok": False,
        "error": last_error or "unknown download error",
        "attempts": retries,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--first-chapter", type=int, default=1)
    parser.add_argument("--last-chapter", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    if args.first_chapter < 1 or args.last_chapter < args.first_chapter:
        parser.error("invalid chapter range")
    if not 1 <= args.workers <= 32:
        parser.error("workers must be between 1 and 32")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chapters = list(range(args.first_chapter, args.last_chapter + 1))

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(fetch_one, args.year, chapter, output_dir, args.retries, args.timeout)
            for chapter in chapters
        ]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            status = "ok" if result["ok"] else "FAILED"
            print(f'{result["id"]}: {status}', flush=True)

    results.sort(key=lambda item: item["chapter"])
    failures = [item for item in results if not item["ok"]]
    report = {
        "schemaVersion": 1,
        "sessionYear": args.year,
        "firstChapter": args.first_chapter,
        "lastChapter": args.last_chapter,
        "expectedDocuments": len(chapters),
        "acquiredDocuments": sum(1 for item in results if item["ok"]),
        "valid": not failures and len(results) == len(chapters),
        "documents": results,
        "failures": failures,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "valid": report["valid"],
        "expectedDocuments": report["expectedDocuments"],
        "acquiredDocuments": report["acquiredDocuments"],
        "failureCount": len(failures),
    }, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
