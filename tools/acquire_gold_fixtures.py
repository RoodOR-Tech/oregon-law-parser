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


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    repo_root = Path(args.repo_root)
    manifest = json.loads(Path(args.manifest).read_text())
    acquired = []
    errors = []
    context = ssl.create_default_context()

    for item in manifest.get("documents", []):
        fixture = repo_root / item["fixture"]
        source_url = item["sourceUrl"]
        expected_hash = item.get("sourceSha256")
        host = urlparse(source_url).hostname

        if host not in ALLOWED_HOSTS:
            errors.append(f'{item["id"]}: source host not allowlisted: {host!r}')
            continue

        if fixture.exists():
            data = fixture.read_bytes()
            digest = sha256_bytes(data)
            status = "existing"
        else:
            fixture.parent.mkdir(parents=True, exist_ok=True)
            try:
                request = urllib.request.Request(source_url, headers={"User-Agent": "oregon-law-parser-gold-corpus/1"})
                with urllib.request.urlopen(request, context=context, timeout=60) as response:
                    data = response.read()
            except Exception as exc:
                errors.append(f'{item["id"]}: download failed: {exc}')
                continue
            if not data.startswith(b"%PDF"):
                errors.append(f'{item["id"]}: downloaded source is not a PDF')
                continue
            digest = sha256_bytes(data)
            fixture.write_bytes(data)
            status = "downloaded"

        if expected_hash and digest != expected_hash:
            errors.append(f'{item["id"]}: SHA-256 mismatch: expected {expected_hash}, got {digest}')

        acquired.append({
            "id": item["id"],
            "fixture": item["fixture"],
            "status": status,
            "sha256": digest,
            "hashPinned": bool(expected_hash),
        })

    report = {
        "schemaVersion": 1,
        "valid": not errors,
        "documents": acquired,
        "errors": errors,
    }
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
