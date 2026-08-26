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

BASE_URL = "https://www.oregonlegislature.gov/bills_laws/lawsstatutes/{year}orlaw{chapter:04d}.pdf"
USER_AGENT = "oregon-law-parser-session-scale/1"


def fetch_one(year, chapter, output_dir, retries, timeout):
    doc_id = f"{year}orlaw{chapter:04d}"
    url = BASE_URL.format(year=year, chapter=chapter)
    path = output_dir / f"{doc_id}.pdf"
    context = ssl.create_default_context()
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
                data = response.read()
            if not data.startswith(b"%PDF"):
                return {
                    "id": doc_id,
                    "chapter": chapter,
                    "sourceUrl": url,
                    "ok": False,
                    "error": "downloaded source is not a PDF",
                }
            digest = hashlib.sha256(data).hexdigest()
            path.write_bytes(data)
            return {
                "id": doc_id,
                "chapter": chapter,
                "sourceUrl": url,
                "fixture": str(path),
                "ok": True,
                "sha256": digest,
                "bytes": len(data),
                "attempts": attempt,
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    return {
        "id": doc_id,
        "chapter": chapter,
        "sourceUrl": url,
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
