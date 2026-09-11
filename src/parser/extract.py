"""PDF reading order and styled text; no Java or external executables."""
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from io import BytesIO
import re
import unicodedata
import gzip
import json
from pathlib import Path
from itertools import groupby
from operator import itemgetter

import pdfplumber

EXTRACTION_FINGERPRINT = Path(__file__).read_bytes()


@dataclass
class Document:
    text: str
    styles: list  # one (bold, underline) pair per normalized character
    edition_years: tuple = ()  # independently printed PDF running-footer years
    chapter_heading: tuple = ()

    def slice(self, start, end=None):
        return Document(self.text[start:end], self.styles[start:end], self.edition_years, self.chapter_heading)


def normalize(items):
    """Collapse whitespace and ligatures without losing style alignment."""
    chars, styles = [], []
    for text, bold, underline in items:
        for c in unicodedata.normalize("NFKC", text).replace("\u00ad", ""):
            if c.isspace():
                c = "\n" if c == "\n" else " "
                if chars and chars[-1].isspace():
                    if c == "\n":
                        chars[-1] = "\n"
                    continue
            chars.append(c)
            styles.append((bold, underline))
    # Join only line-end hyphenation, keeping visible compound hyphens elsewhere.
    text = "".join(chars)
    remove = set()
    for m in re.finditer(r"(?<=[A-Za-z])-\n(?=[a-z])", text):
        remove.update(range(m.start(), m.end()))
    return Document("".join(c for i, c in enumerate(chars) if i not in remove),
                    [s for i, s in enumerate(styles) if i not in remove])


def _lines(chars):
    result = []
    for c in sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"])):
        if not result or abs(c["top"] - result[-1][0]["top"]) > 2:
            result.append([c])
        else:
            result[-1].append(c)
    return [sorted(line, key=lambda c: c["x0"]) for line in result]


def _line_text(line):
    parts = []
    for i, char in enumerate(line):
        if i and char["x0"] - line[i-1]["x1"] > 1.5:
            parts.append(" ")
        parts.append(char["text"])
    return " ".join("".join(parts).split())


def deduplicate_chars(chars):
    """Same clustering as pdfplumber, without its quadratic chars.index sort."""
    key = itemgetter('upright', 'text', 'fontname', 'size')
    positions = {id(char): i for i, char in enumerate(chars)}
    result = []
    for _, group in groupby(sorted(chars, key=key), key=key):
        for row in pdfplumber.utils.cluster_objects(list(group), itemgetter('doctop'), 1):
            for cluster in pdfplumber.utils.cluster_objects(row, itemgetter('x0'), 1):
                result.append(min(cluster, key=itemgetter('doctop', 'x0')))
    return sorted(result, key=lambda char: positions[id(char)])


def reading_regions(chars, mid, heading_bottom=0):
    """Read columns within horizontal bands separated by full-width rules.

    ORS switches from columns to forms/tables at printed underscore rules.
    A continuous text run across the gutter marks a full-width band. Title
    front matter is explicitly bounded by the printed chapter heading.
    """
    lines = _lines(chars)
    left, right = min(c['x0'] for c in chars), max(c['x1'] for c in chars)
    rules = [line for line in lines if re.fullmatch(r'[_\-]{10,}', _line_text(line))
             and line[0]['x0'] < mid < line[-1]['x1']
             and line[-1]['x1'] - line[0]['x0'] > (right-left)*.75]
    boundaries = sorted({heading_bottom} | {line[0]['top'] for line in rules}
                        | {max(c['bottom'] for c in line) for line in rules})
    bands = []
    previous = float('-inf')
    for stop in boundaries + [float('inf')]:
        band = [c for c in chars if previous <= c['top'] < stop]
        previous = stop
        if not band:
            continue
        band_lines = _lines(band)
        # Do not mistake a near-gutter edge for crossing: require actual
        # characters spanning both sides of the gutter within one text run.
        crosses = any(any(c['x0'] < mid < c['x1'] and c['text'].strip()
                          for c in line) for line in band_lines)
        if stop <= heading_bottom or crosses:
            bands.append(band)
        else:
            bands.extend([[c for c in band if c['x0'] < mid],
                          [c for c in band if c['x0'] >= mid]])
    return bands


def pdf_document(data, columns=2, running_headers=True, cache_dir=None):
    if cache_dir is not None:
        from .cache import digest, atomic_write
        # Invalidate derived text whenever extraction code or options change.
        key = digest(data + EXTRACTION_FINGERPRINT + pdfplumber.__version__.encode()
                     + str((columns, running_headers)).encode())
        cached = Path(cache_dir) / (key + '.json.gz')
        if cached.exists():
            return Document(**json.loads(gzip.decompress(cached.read_bytes())))
        document = pdf_document(data, columns, running_headers)
        atomic_write(cached, gzip.compress(json.dumps(document.__dict__, ensure_ascii=False).encode(), mtime=0))
        return document
    if columns not in (1, 2):
        raise ValueError('PDF columns must be 1 or 2')
    items = []
    edition_years = set()
    chapter_heading = ()
    with pdfplumber.open(BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages):
            underline_edges = [edge for edge in page.edges if abs(edge["top"] - edge["bottom"]) < .8
                               and edge["x1"] - edge["x0"] < page.width * .6]
            chars = deduplicate_chars(page.chars)
            if not chars:
                if not page.images:
                    page.close()
                    continue  # a genuinely blank page, not an image-only scan
                raise ValueError(f"PDF page {page_no + 1} has no text layer; OCR is required")
            # Running headers/footers establish the binding margins even when
            # an indented statutory form leaves one body column unusually narrow.
            page_mid = (min(c['x0'] for c in chars) + max(c['x1'] for c in chars)) / 2
            header_rules = [e for e in page.edges if abs(e['top']-e['bottom']) < 1
                            and e['top'] < 110 and e['x1']-e['x0'] > page.width*.65]
            if header_rules:
                rule = max(header_rules, key=lambda e: e['x1']-e['x0'])
                page_mid = (rule['x0']+rule['x1'])/2
            all_lines = _lines(chars)
            heading_bottom = 0
            if not chapter_heading:
                for index, line in enumerate(all_lines[:-2]):
                    chapter = re.fullmatch(r'Chapter\s+(\d+[A-Z]?)', _line_text(line))
                    if chapter and re.fullmatch(r'\d{4}\s+EDITION|\(Former Provisions\)', _line_text(all_lines[index+1])):
                        title_lines = [all_lines[index+2]]
                        title_size = max(c['size'] for c in title_lines[0])
                        for following in all_lines[index+3:]:
                            if abs(max(c['size'] for c in following) - title_size) > .3 or following[0]['top'] - title_lines[-1][0]['top'] > title_size * 2:
                                break
                            title_lines.append(following)
                        chapter_heading = (chapter[1], ' '.join(_line_text(row) for row in title_lines))
                        heading_bottom = max(c['bottom'] for c in title_lines[-1]) + 1
                        break
            if running_headers:
                # Preserve the first session-law header for identity, remove repetitions.
                first_text = _line_text(all_lines[0])
                is_law = bool(re.search(r"OREGON LAWS\s+\d{4}", first_text, re.I))
                if is_law and page_no == 0:
                    items.append((first_text + "\n", False, False))
                is_running_header = header_rules and max(c['bottom'] for c in all_lines[0]) <= max(e['top'] for e in header_rules) + 1
                if is_law or is_running_header:
                    top = max(c["bottom"] for c in all_lines[0]) + 1
                    chars = [c for c in chars if c["top"] >= top]
                # Published page footers include Title / Page / (YYYY Edition), or page number.
                footer = [line for line in all_lines if line[0]["top"] > page.height * .90
                          and re.search(r"(?:Title\s+\d+.*Page|^\s*\d+\s*$)", _line_text(line))]
                if footer:
                    for line in footer:
                        edition_years.update(int(y) for y in re.findall(r"\((\d{4})\s+Edition\)", _line_text(line)))
                    bottom = min(c["top"] for line in footer for c in line)
                    chars = [c for c in chars if c["top"] < bottom]
            if not chars:
                page.close()
                continue  # printed blank verso carrying only running header/footer
            regions = [chars]
            if columns == 2:
                regions = reading_regions(chars, page_mid, heading_bottom)
            for region in regions:
                for line in _lines(region):
                    previous = None
                    for c in line:
                        if previous and c["x0"] - previous["x1"] > max(1.5, c["size"] * .18):
                            items.append((" ", bool(re.search("bold|black|demi", c["fontname"], re.I)), False))
                        underline = any(abs(edge["top"] - c["bottom"]) <= 2.5
                                        and edge["x0"] <= c["x0"] + 1 and edge["x1"] >= c["x1"] - 1
                                        for edge in underline_edges)
                        items.append((c["text"], bool(re.search("bold|black|demi", c["fontname"], re.I)), underline))
                        previous = c
                    items.append(("\n", False, False))
            page.close()
    document = normalize(items)
    document.edition_years = tuple(sorted(edition_years))
    document.chapter_heading = chapter_heading
    return document


class StyledHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.items, self.hidden = [], [], 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        style = attrs.get("style", "").lower()
        bold = tag in ("b", "strong") or bool(re.search(r"font-weight\s*:\s*(?:bold|[7-9]00)", style))
        underline = tag in ("u", "ins") or "underline" in style
        if tag not in ("br", "meta", "link", "img", "hr", "input"):
            self.stack.append((tag, bold, underline))
        if tag in ("p", "div", "br", "h1", "h2", "li", "tr"):
            self.items.append(("\n", False, False))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in ("p", "div", "h1", "h2", "li", "tr"):
            self.items.append(("\n", False, False))

    def handle_data(self, text):
        if not self.hidden:
            self.items.append((text, any(s[1] for s in self.stack), any(s[2] for s in self.stack)))


def html_document(markup):
    reader = StyledHTML()
    reader.feed(markup)
    return normalize(reader.items)


def document_markup(doc):
    """Reconstruct style runs for the established ORS HTML parser.

    Line wrapping inside a bold catchline remains one run. Paragraph starts
    are section/Note headings; source line breaks otherwise become spaces.
    """
    out, current = ["<p>"], False
    paragraph_start = re.compile(r"(?:\d+[A-Z]?\.\d{3,4}\s|Notes?:|Chapter\s|\d{4}\s+EDITION)")
    for i, c in enumerate(doc.text):
        bold = doc.styles[i][0]
        if c == "\n":
            if paragraph_start.match(doc.text, i+1):
                if current:
                    out.append("</b>")
                    current = False
                out.append("</p><p>")
            else:
                out.append(" ")
            continue
        if bold != current:
            out.append("<b>" if bold else "</b>")
            current = bold
        out.append(escape(c))
    if current:
        out.append("</b>")
    return "".join(out) + "</p>"
