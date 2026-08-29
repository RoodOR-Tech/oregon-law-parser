#!/usr/bin/env python3
import argparse
import hashlib
import json
import ssl
import sys
import time
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


def source_format(data):
    if data.startswith(b"%PDF"):
        return "pdf"
    prefix = data[:4096].lstrip().lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html") or b"<html" in prefix:
        return "html"
    return None


def expected_format(fixture):
    suffix = fixture.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".html", ".htm"}:
        return "html"
    return None


def download_source(source_url, context, retries, timeout):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                source_url,
                headers={"User-Agent": "oregon-law-parser-gold-corpus/1"},
            )
            with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
                return response.read(), attempt
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"failed after {retries} attempts: {last_error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--report", required=True)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    if args.retries < 1:
        parser.error("--retries must be at least 1")
    if args.timeout < 1:
        parser.error("--timeout must be at least 1")

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
        fixture_format = expected_format(fixture)
        download_attempts = 0

        if host not in ALLOWED_HOSTS:
            errors.append(f'{item["id"]}: source host not allowlisted: {host!r}')
            continue
        if fixture_format is None:
            errors.append(f'{item["id"]}: unsupported fixture extension: {fixture.suffix!r}')
            continue

        if fixture.exists():
            data = fixture.read_bytes()
            digest = sha256_bytes(data)
            status = "existing"
        else:
            fixture.parent.mkdir(parents=True, exist_ok=True)
            try:
                data, download_attempts = download_source(
                    source_url,
                    context,
                    args.retries,
                    args.timeout,
                )
            except Exception as exc:
                errors.append(f'{item["id"]}: download failed: {exc}')
                continue

            actual_format = source_format(data)
            if actual_format != fixture_format:
                errors.append(
                    f'{item["id"]}: downloaded source format {actual_format!r} does not match fixture format {fixture_format!r}'
                )
                continue
            digest = sha256_bytes(data)
            fixture.write_bytes(data)
            status = "downloaded"

        actual_format = source_format(data)
        if actual_format != fixture_format:
            errors.append(
                f'{item["id"]}: fixture format {actual_format!r} does not match expected format {fixture_format!r}'
            )
            continue

        if expected_hash and digest != expected_hash:
            errors.append(f'{item["id"]}: SHA-256 mismatch: expected {expected_hash}, got {digest}')

        acquired.append({
            "id": item["id"],
            "fixture": item["fixture"],
            "sourceFormat": actual_format,
            "status": status,
            "sha256": digest,
            "hashPinned": bool(expected_hash),
            "downloadAttempts": download_attempts,
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
