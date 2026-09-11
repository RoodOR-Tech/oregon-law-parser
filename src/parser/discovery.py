"""Discover publications from public indexes; validate identity after fetching.

    SharePoint's anonymous archive page publishes group metadata but its REST
    list API is not public. The documented filename convention is a locator,
    never evidence for the edition stored in the database.
"""
import json
import re
from html import unescape
from io import BytesIO
from urllib.parse import urljoin
from urllib.error import HTTPError

import pdfplumber
from ors.tools.acquire_ors_roster import parse_table_of_titles
from ors.tools.enumerate_ors_chapters import candidate_digit_range, covering_title

ORS_INDEX = "https://www.oregonlegislature.gov/bills_laws/Pages/ORS.aspx"
ARCHIVE_INDEX = "https://www.oregonlegislature.gov/bills_laws/pages/orsarchive.aspx"
LAWS_INDEX = "https://www.oregonlegislature.gov/bills_laws/Pages/Oregon-Laws.aspx"


def links(markup, base):
    return sorted({urljoin(base, unescape(h)) for h in re.findall(r'href=["\']([^"\']+)', markup, re.I)})


def discover(cache, year, chapters=None, session_limit=None, log=lambda _: None):
    index = cache.get(ORS_INDEX).decode("utf-8", errors="replace")
    current = re.search(r"ORS\).*?[-–]\s*(\d{4})\s+Edition", re.sub(r"<[^>]+>", "", index), re.S | re.I)
    archive = cache.get(ARCHIVE_INDEX).decode("utf-8", errors="replace")
    archived_years = {int(y) for y in re.findall(r'"Label"\s*:\s*"(\d{4})"', archive)}
    archived_years.update(int(y) for y in re.findall(r'groupString="%3B%23(\d{4})%3B%23"', archive, re.I))
    if year not in archived_years and (not current or int(current[1]) != year):
        raise ValueError(f"edition {year} is not advertised by the official indexes")
    archived = year in archived_years
    root = re.search(r'ctx\.listUrlDir\s*=\s*"([^"]+)"', archive)
    if archived and not root:
        raise ValueError("archive index contains no document library metadata")
    # The index's linked roster provides candidate ranges, not proof of edition.
    roster_url = next((u for u in links(index, ORS_INDEX) if "ORS_TitlesChapters.pdf" in u), None)
    if not roster_url:
        raise ValueError("ORS index does not link a table of titles")
    roster_data = cache.get(roster_url)
    with pdfplumber.open(BytesIO(roster_data)) as pdf:
        pages = []
        for page in pdf.pages:
            labels = [w["x0"] for w in page.extract_words() if w["text"] == "Title"]
            if not labels:
                if re.fullmatch(r"[ivxlcdm\s]+", page.extract_text() or "", re.I):
                    continue
                raise ValueError("table-of-titles page has no title column")
            pages.append(page.crop((min(labels) - 1, 0, page.width, page.height)).extract_text() or "")
        roster_text = "\n".join(pages)
    volumes, titles, unparsed, unresolved = parse_table_of_titles(roster_text)
    if not titles or unparsed or unresolved:
        raise ValueError("table of titles could not be parsed completely")
    docs = []

    def probe(number, required=False):
        digits = re.match(r"\d+", number)[0]
        stem = f"{int(digits):03d}" + number[len(digits):]
        if archived:
            url = urljoin(ARCHIVE_INDEX, root[1].rstrip("/") + f"/{year}ors{stem}.pdf")
        else:
            chapter_links = [u for u in links(index, ORS_INDEX) if re.search(rf"/ors{stem}\.html$", u, re.I)]
            url = chapter_links[0] if chapter_links else urljoin(roster_url, f"../ors/ors{stem}.html")
        try:
            data = cache.get(url)
        except HTTPError as error:
            if error.code == 404 and not required:
                return False
            raise
        title = covering_title(number, titles)
        docs.append({"kind": "chapter", "chapter_number": number, "source_url": url,
                     "sha256": cache.sources[url]["sha256"],
                     # Current volume membership is not historical evidence.
                     "volume_number": title.get("volumeNumber") if title and not archived else None})
        log(f"Discovered chapter {number} ({len(data)} bytes)")
        return True

    if chapters:
        for number in sorted(set(chapters)):
            probe(number, required=True)
    else:
        # Historical chapters can lie outside today's title ranges. Probe the
        # entire numeric namespace through the largest published endpoint.
        candidates = candidate_digit_range(titles)
        if archived:
            candidates = range(1, max(candidates) + 1)
        for number in candidates:
            probe(str(number))
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if not probe(str(number) + letter):
                    break
    if not docs:
        raise ValueError("no ORS chapters discovered")
    laws_index = cache.get(LAWS_INDEX).decode("utf-8", errors="replace")
    law_root = re.search(r'ctx\.listUrlDir\s*=\s*"([^"]+)"', laws_index)
    if not law_root:
        raise ValueError("session-law index contains no document library metadata")
    # Discover the year-specific comparative table link from the live ORS page.
    comparative = next((u for u in links(index, ORS_INDEX) if re.search(rf"/ors/{year}\.pdf$", u, re.I)), None)
    if not comparative:
        raise ValueError(f"no published comparative table for session {year}")
    with pdfplumber.open(BytesIO(cache.get(comparative))) as pdf:
        law_chapters = set()
        for page in pdf.pages:
            # Each row begins with an Oregon Laws chapter and section; the ORS
            # column follows. A chapter integer is followed by '.' in this table.
            for match in re.finditer(r"(?<![\d.])(\d+)\.{2,8}\d+(?:[-,]\d+)?\.{2,}", page.extract_text() or ""):
                law_chapters.add(int(match[1]))
    if not law_chapters:
        raise ValueError("no session chapters in comparative table; supply a pinned --manifest")
    count = max(law_chapters)
    for chapter in range(1, min(count, session_limit or count) + 1):
        url = urljoin(LAWS_INDEX, law_root[1].rstrip("/") + f"/{year}orlaw{chapter:04d}.pdf")
        data = cache.get(url)
        docs.append({"kind": "session", "source_url": url, "session_year": year,
                     "sha256": cache.sources[url]["sha256"], "special_session": 0})
        log(f"Discovered session chapter {chapter}/{count}")
    return {"schema_version": 1, "edition_year": year, "source_url": ARCHIVE_INDEX if archived else ORS_INDEX,
            "scope": "selected" if chapters or session_limit else "discovered",
            "notes": "Archive volume numbers remain unknown; supplements are separate session sources.",
            "documents": docs, "provenance": sorted(cache.sources.values(), key=lambda r: r["source_url"])}


def load_manifest(path):
    from pathlib import Path
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("documents"), list):
        raise ValueError("manifest requires schema_version=1 and a documents array")
    for record in manifest["documents"]:
        if "path" in record:
            record["source_url"] = (path.parent / record.pop("path")).resolve().as_uri()
        if not record.get("source_url") or record.get("kind") not in ("chapter", "session"):
            raise ValueError("each document needs a kind and source_url or path")
    return manifest
