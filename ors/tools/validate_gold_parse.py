"""Require a complete, valid parse of the frozen gold chapter selection."""
import argparse
import json
from pathlib import Path


def validate(report, selection, exit_code):
    errors = []
    if exit_code != 0:
        errors.append(f"unexpected parser exit code: {exit_code}")
    for field in ("problems", "integrityViolations", "unreadable", "chaptersWithoutName"):
        if report.get(field) != []:
            errors.append(f"{field} is missing or nonempty")
    for field in ("unreadableChapterCount", "editorialNoteCandidateCount"):
        if report.get(field) != 0:
            errors.append(f"{field} must be zero")
    expected = sorted(item["chapterNumber"] for item in selection["chapters"])
    actual = sorted(item["chapterNumber"] for item in report.get("perChapter", []))
    if actual != expected or report.get("parsedChapterCount") != len(expected):
        errors.append("parsed chapters differ from frozen selection")
    if report.get("sectionRowCount", 0) <= 0:
        errors.append("no section rows")
    if report.get('unparsedCreditSegments') != [] or report.get('unparsedCreditSegmentCount') != 0:
        errors.append('unparsed credit segments are not allowed')
    if report.get("valid") is not True:
        errors.append("parser must report valid: true")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    args = parser.parse_args()
    load = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate(load(args.report), load(args.selection), args.exit_code)
    print(json.dumps({"valid": not errors, "failures": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
