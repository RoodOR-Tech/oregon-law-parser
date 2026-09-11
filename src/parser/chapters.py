"""Adapt the established ORS parser to HTML and style-preserving PDFs."""
from html import escape
import re

from ors.tools.parse_ors_chapter import parse_chapter, split_source_credit
from ors.tools.ors_text import decode_markup, declared_charset
from .extract import pdf_document, document_markup, html_document
from .identity import edition_identity
from .notes import split_bracket_notes


def parse_source(data, number, year, columns=2, cache_dir=None):
    collective_credit = None
    chapter_notes = []
    if data.startswith(b"%PDF"):
        doc = pdf_document(data, columns=columns, cache_dir=cache_dir)
        identity = edition_identity(doc.text + '\n' + '\n'.join(f'{y} EDITION' for y in doc.edition_years), year)
        heading = re.search(rf"(?m)^Chapter\s+{re.escape(number)}\s*\n(?:\d{{4}}\s+EDITION|\(Former Provisions\))\s*\n([^\n]+)", doc.text)
        if heading is None:
            raise ValueError(f"missing printed PDF chapter heading for {number}")
        title = doc.chapter_heading[1] if doc.chapter_heading and doc.chapter_heading[0] == number else heading[1]
        # The printed contents repeat the section roster, often also in bold.
        # A body anchor repeats a prior contents entry; TOC entries are not law.
        seen, body_start = set(), None
        anchors = list(re.finditer(rf'''(?m)^({re.escape(number)}\.\d{{3,4}})[ \t]+(?=[A-Z“‘"'\[])''', doc.text))
        for anchor in anchors:
            if anchor[1] == anchors[0][1] and anchor[1] in seen and doc.styles[anchor.start()][0]:
                body_start = anchor.start()
                break
            seen.add(anchor[1])
        if body_start is None:
            if '(Former Provisions)' in doc.text and anchors and all(doc.text[a.end():].startswith('[') for a in anchors):
                body_start = anchors[0].start()
            elif '(Former Provisions)' in doc.text:
                notice = re.search(r'Note:\s+(.+?)(?=\n(?:CHAPTERS?\s+\d|TITLE\s+\d)|\Z)', doc.text, re.S)
                listing = re.match(rf'(?:{re.escape(number)}\.\d{{3,4}}[,\s]*(?:and\s+)?)+', notice[1]) if notice else None
                numbers = re.findall(rf'{re.escape(number)}\.\d{{3,4}}', listing[0]) if listing else []
                if not numbers:
                    raise ValueError(f'former chapter {number} has no explicit section dispositions')
                collective_credit = ' '.join(notice[0].split())
                disposition = ' '.join(notice[1][listing.end():].split())
                body_markup = ''.join(f'<p><b>{section}</b> [{escape(disposition)}]</p>' for section in dict.fromkeys(numbers))
            elif re.search(r'is compiled as a note\)', doc.text):
                # Chapter 259 publishes an uncodified measure, not numbered ORS.
                # Preserve its full text without inventing ORS section numbers.
                chapter_notes.append(doc.text)
                body_markup = ''
            else:
                raise ValueError(f"cannot separate PDF contents and statutory body for chapter {number}")
        if body_start is not None:
            body_markup = document_markup(doc.slice(body_start))
        markup = (f"<p>Chapter {escape(number)} — {escape(title)}</p><p>{year} EDITION</p>"
                  + body_markup)
    else:
        markup, _ = decode_markup(data, declared_charset(data))
        doc = html_document(markup)
        identity = edition_identity(doc.text, year)
    parsed = parse_chapter(markup, number, preserve_versions=True)
    if parsed["editionYear"] != year or parsed["printedChapterNumber"] != number:
        raise ValueError(f"printed chapter/edition identity mismatch for chapter {number}")
    if parsed["problems"]:
        raise ValueError(f"chapter {number}: {'; '.join(parsed['problems'][:5])}")
    if not parsed["sections"] and not chapter_notes:
        raise ValueError(f"chapter {number} produced no sections")
    for section in parsed["sections"]:
        if collective_credit:
            section['sourceCreditRaw'] = collective_credit
        body, bracket_notes = split_bracket_notes(section["bodyText"] or "")
        body, credit = split_source_credit(body)
        section["bodyText"] = body or None
        if credit and not section["sourceCreditRaw"]:
            section["sourceCreditRaw"] = credit
        section["notes"].extend({"text": n["text"], "charOffsetStart": None, "charOffsetEnd": None} for n in bracket_notes)
    parsed["identity"] = identity
    parsed['chapterNotes'] = chapter_notes
    return parsed
