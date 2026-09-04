"""Keep the section benchmark's known credit gaps from masking other failures."""
import argparse
import json
from pathlib import Path


KNOWN_CREDIT_GAPS = {
    ("2025-471.410", "1983 cor. c.736 §1"),
    ("2025-471.420", "repealed by 1979 c.43 §1 and by 1979 c.190 §431"),
    ("2025-471.666", "enacted in lieu of 471.665 in 1997"),
    ("2025-471.750", "amendments by 2002 s.s.1 c.11 §1 repealed by 2002 s.s.2 c.1 §3"),
}


def validate(report, selection, exit_code):
    errors = []
    if exit_code not in (0, 1):
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
    gaps = [(item["sectionId"], segment)
            for item in report["unparsedCreditSegments"] for segment in item["segments"]]
    if len(gaps) != len(set(gaps)) or not set(gaps) <= KNOWN_CREDIT_GAPS:
        errors.append("unrecognized or duplicate credit gaps")
    if report.get("unparsedCreditSegmentCount") != len(gaps):
        errors.append("credit gap count mismatch")
    if report.get("valid") is not (not gaps) or exit_code != int(bool(gaps)):
        errors.append("parser validity/exit code does not match known credit gaps")
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
