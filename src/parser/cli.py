"""python -m parser.cli run --year 2023 --output ./dist/ors_data.db"""
import argparse
import json
from pathlib import Path
import sys
import sqlite3

from .cache import Cache, atomic_write
from .database import export_parquet
from .discovery import discover, load_manifest
from .pipeline import build


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="acquire, parse and atomically publish SQLite")
    run.add_argument("--year", type=int, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--manifest", type=Path, help="pinned source list; local paths are relative to this file")
    run.add_argument("--cache", type=Path, default=Path(".ors-cache"))
    run.add_argument("--offline", action="store_true")
    run.add_argument("--refresh", action="store_true")
    run.add_argument("--chapters", help="comma-separated chapter selection (marks output as selected)")
    run.add_argument("--session-limit", type=int, help="limit session documents (marks output as selected)")
    run.add_argument("--parquet-dir", type=Path)
    run.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    if args.manifest and (args.chapters or args.session_limit):
        parser.error("--chapters/--session-limit cannot be combined with --manifest")
    if args.session_limit is not None and args.session_limit < 1:
        parser.error("--session-limit must be positive")
    log = (lambda text: print(text, file=sys.stderr, flush=True)) if not args.quiet else (lambda _: None)
    try:
        cache = Cache(args.cache, args.offline, args.refresh)
        if args.parquet_dir:
            import duckdb  # fail before publishing SQLite if optional dependency is absent
        manifest = load_manifest(args.manifest) if args.manifest else discover(
            cache, args.year, args.chapters.split(",") if args.chapters else None, args.session_limit, log)
        if manifest["edition_year"] != args.year:
            raise ValueError("manifest edition does not match --year")
        report = build(manifest, cache, args.output, log)
        if args.parquet_dir:
            export_parquet(args.output, args.parquet_dir)
        atomic_write(args.output.with_suffix(".manifest.json"), json.dumps(manifest, indent=2, sort_keys=True).encode())
        atomic_write(args.output.with_suffix(".report.json"), json.dumps(report, indent=2, sort_keys=True).encode())
        print(json.dumps(report, sort_keys=True))
        return 0
    except (ValueError, OSError, ImportError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
