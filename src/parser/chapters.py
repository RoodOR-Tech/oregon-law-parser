"""Adapt the established ORS parser to HTML and style-preserving PDFs."""
from html import escape
import re

from ors.tools.parse_ors_chapter import parse_chapter, split_source_credit
from ors.tools.ors_text import decode_markup, declared_charset
from .extract import pdf_document, document_markup, html_document
from .identity import edition_identity
from .notes import split_bracket_notes


def parse_source(data, number, year, columns=2):
    if data.startswith(b"%PDF"):
        doc = pdf_document(data, columns=columns)
        identity = edition_identity(doc.text, year)
        heading = re.search(rf"(?m)^Chapter\s+{re.escape(number)}\s*\n\d{{4}}\s+EDITION\s*\n([^\n]+)", doc.text)
        if heading is None:
            raise ValueError(f"missing printed PDF chapter heading for {number}")
        # The printed contents repeat the section roster, often also in bold.
        # A body anchor repeats a prior contents entry; TOC entries are not law.
        seen, body_start = set(), None
        anchors = list(re.finditer(rf"(?m)^({re.escape(number)}\.\d{{3}})[ \t]+(?=\S)", doc.text))
        for anchor in anchors:
            if anchor[1] in seen and doc.styles[anchor.start()][0]:
                body_start = anchor.start()
                break
            seen.add(anchor[1])
        if body_start is None:
            raise ValueError(f"cannot separate PDF contents and statutory body for chapter {number}")
        markup = (f"<p>Chapter {escape(number)} — {escape(heading[1])}</p><p>{year} EDITION</p>"
                  + document_markup(doc.slice(body_start)))
    else:
        markup, _ = decode_markup(data, declared_charset(data))
        doc = html_document(markup)
        identity = edition_identity(doc.text, year)
    parsed = parse_chapter(markup, number)
    if parsed["editionYear"] != year or parsed["printedChapterNumber"] != number:
        raise ValueError(f"printed chapter/edition identity mismatch for chapter {number}")
    if parsed["problems"]:
        raise ValueError(f"chapter {number}: {'; '.join(parsed['problems'][:5])}")
    if not parsed["sections"]:
        raise ValueError(f"chapter {number} produced no sections")
    for section in parsed["sections"]:
        body, bracket_notes = split_bracket_notes(section["bodyText"] or "")
        body, credit = split_source_credit(body)
        section["bodyText"] = body or None
        if credit and not section["sourceCreditRaw"]:
            section["sourceCreditRaw"] = credit
        section["notes"].extend({"text": n["text"], "charOffsetStart": None, "charOffsetEnd": None} for n in bracket_notes)
    parsed["identity"] = identity
    return parsed
