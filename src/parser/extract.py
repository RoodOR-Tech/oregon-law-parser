"""PDF reading order and styled text; no Java or external executables."""
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from io import BytesIO
import re
import unicodedata

import pdfplumber


@dataclass
class Document:
    text: str
    styles: list  # one (bold, underline) pair per normalized character

    def slice(self, start, end=None):
        return Document(self.text[start:end], self.styles[start:end])


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
    return "".join(parts)


def pdf_document(data, columns=2, running_headers=True):
    items = []
    with pdfplumber.open(BytesIO(data)) as pdf:
        for page_no, page in enumerate(pdf.pages):
            underline_edges = [edge for edge in page.edges if abs(edge["top"] - edge["bottom"]) < .8
                               and edge["x1"] - edge["x0"] < page.width * .6]
            chars = page.dedupe_chars().chars
            if not chars:
                raise ValueError(f"PDF page {page_no + 1} has no text layer; OCR is required")
            all_lines = _lines(chars)
            if running_headers:
                # Preserve the first session-law header for identity, remove repetitions.
                first_text = _line_text(all_lines[0])
                is_law = bool(re.search(r"OREGON LAWS\s+\d{4}", first_text))
                if is_law and page_no == 0:
                    items.append((first_text + "\n", False, False))
                if is_law or page_no > 0:
                    top = max(c["bottom"] for c in all_lines[0]) + 1
                    chars = [c for c in chars if c["top"] >= top]
                # Published page footers include Title / Page / (YYYY Edition), or page number.
                footer = [line for line in all_lines if line[0]["top"] > page.height * .90
                          and re.search(r"(?:Title\s+\d+.*Page|^\s*\d+\s*$)", _line_text(line))]
                if footer:
                    bottom = min(c["top"] for line in footer for c in line)
                    chars = [c for c in chars if c["top"] < bottom]
            if not chars:
                continue  # printed blank verso carrying only running header/footer
            regions = [chars]
            if columns == 2:
                mid = (min(c["x0"] for c in chars) + max(c["x1"] for c in chars)) / 2
                # Full-width chapter/title front matter must precede both columns.
                crossing = [line for line in _lines(chars)
                            if any(c["x0"] < mid + 3 and c["x1"] > mid - 3 for c in line)]
                split_top = max((max(c["bottom"] for c in line) for line in crossing), default=0)
                if split_top > page.height * .65:
                    raise ValueError(f"ambiguous two-column PDF layout on page {page_no + 1}; specify columns=1 in the manifest")
                regions = [[c for c in chars if c["top"] < split_top],
                           [c for c in chars if c["top"] >= split_top and c["x0"] < mid],
                           [c for c in chars if c["top"] >= split_top and c["x0"] >= mid]]
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
    return normalize(items)


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
    for i, c in enumerate(doc.text):
        bold = doc.styles[i][0]
        if c == "\n":
            following = doc.text[i+1:]
            if re.match(r"(?:\d+[A-Z]?\.\d{3}\s|Notes?:|Chapter\s|\d{4}\s+EDITION)", following):
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
