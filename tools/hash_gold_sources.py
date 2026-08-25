#!/usr/bin/env python3
import argparse
import hashlib
import json
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_HOSTS = {
    "www.oregonlegislature.gov",
    "oregonlegislature.gov",
    "olis.oregonlegislature.gov",
}


def source_format(data):
    if data.startswith(b"%PDF"):
        return "pdf"
    prefix = data[:4096].lstrip().lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html") or b"<html" in prefix:
        return "html"
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    candidates = json.loads(Path(args.candidates).read_text())
    context = ssl.create_default_context()
    results = []
    errors = []

    for item in candidates.get("documents", []):
        doc_id = item.get("id")
        source_url = item.get("sourceUrl")
        host = urlparse(source_url or "").hostname
        if host not in ALLOWED_HOSTS:
            errors.append(f"{doc_id}: source host not allowlisted: {host!r}")
            continue
        try:
            request = urllib.request.Request(source_url, headers={"User-Agent": "oregon-law-parser-gold-corpus/1"})
            with urllib.request.urlopen(request, context=context, timeout=60) as response:
                data = response.read()
        except Exception as exc:
            errors.append(f"{doc_id}: download failed: {exc}")
            continue

        fmt = source_format(data)
        if fmt is None:
            errors.append(f"{doc_id}: downloaded source is neither PDF nor recognizable HTML")
            continue

        results.append({
            "id": doc_id,
            "sourceUrl": source_url,
            "sourceFormat": fmt,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })

    report = {"schemaVersion": 1, "valid": not errors, "documents": results, "errors": errors}
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
