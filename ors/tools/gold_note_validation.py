"""Compare editorial note identity and text against frozen source-reviewed notes."""
import argparse
from collections import Counter
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate(review, selection, provenance, rows):
    failures = []
    if review['reviewMethod']['parserNoteOutputConsultedBeforeFreeze'] is not False:
        failures.append('note expectations must be source-reviewed before comparison')
    expected_chapters = {c['chapterNumber'] for c in selection['chapters']}
    reviewed = [c['chapterNumber'] for c in review['chapters']]
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != expected_chapters:
        failures.append('review chapter set differs from frozen selection')
    sources = {c['chapterNumber']: c for c in provenance['documents']}
    expected = {}
    for chapter in review['chapters']:
        source = sources.get(chapter['chapterNumber'], {})
        for left, right in [('sourceSha256', 'sha256'), ('sourceUrl', 'sourceUrl'), ('sourceBytes', 'bytes')]:
            if chapter.get(left) != source.get(right):
                failures.append(f"chapter {chapter['chapterNumber']}: {left} differs from provenance")
        ordinals = Counter()
        for note in chapter['notes']:
            key = (note['sectionId'], note['ordinal'])
            ordinals[note['sectionId']] += 1
            if (key in expected or note['ordinal'] != ordinals[note['sectionId']]
                    or not note['sectionId'].startswith(f"{selection['editionYear']}-{chapter['chapterNumber']}.")
                    or not note['noteText'].strip() or note['noteKind'] != 'editorial_note'):
                failures.append(f'invalid or duplicate expected note: {key}')
            expected[key] = note
    if len(expected) != review['expectedNoteCount']:
        failures.append('expected note count mismatch')
    actual = {}
    for note in rows['sectionNotes']:
        key = (note['sectionId'], note['ordinal'])
        if key in actual:
            failures.append(f'duplicate actual note: {key}')
        if (not isinstance(note.get('charOffsetStart'), int)
                or not isinstance(note.get('charOffsetEnd'), int)
                or note['charOffsetStart'] < 0
                or note['charOffsetEnd'] - note['charOffsetStart'] != len(note['noteText'])):
            failures.append(f'invalid note offsets: {key}')
        actual[key] = note
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    mismatches = []
    for key in sorted(expected.keys() & actual.keys()):
        # Source review explicitly normalizes whitespace; punctuation and
        # words are exact, and attachment/ordinal are part of identity.
        if (expected[key]['noteText'] != ' '.join(actual[key]['noteText'].split())
                or expected[key]['noteKind'] != actual[key]['noteKind']):
            mismatches.append(key)
    if missing or extra or mismatches:
        failures.append('note identity, kind or text differs from source review')
    return {'valid': not failures, 'expectedNoteCount': len(expected), 'actualNoteCount': len(actual),
            'matchedNoteCount': len(expected.keys() & actual.keys()) - len(mismatches),
            'missingNotes': missing, 'extraNotes': extra, 'mismatchedNotes': mismatches, 'failures': failures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('review', 'selection', 'provenance', 'rows', 'report'):
        parser.add_argument('--' + field, required=True)
    args = parser.parse_args()
    report = validate(load(args.review), load(args.selection), load(args.provenance), load(args.rows))
    Path(args.report).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return int(not report['valid'])


if __name__ == '__main__':
    raise SystemExit(main())
