"""Join ORS chapters and session actions into one reproducible database."""
import json
import re

from . import __version__
from .amendments import parse_session
from .cache import digest
from .chapters import parse_source
from .database import write_sqlite
from .extract import pdf_document, html_document
from .notes import explicit_effective_date
from ors.tools.ors_text import decode_markup, declared_charset


def build(manifest, cache, output, log=lambda _: None):
    manifest = dict(manifest, documents=sorted(manifest["documents"], key=lambda r: (r["kind"], r["source_url"])))
    for source in manifest.get("provenance", []):
        cache.get(source["source_url"], source["sha256"])
    year = manifest["edition_year"]
    tables = {name: [] for name in (
        "editions", "chapters", "sections", "amendments", "pending_changes", "sources",
        "chapter_sources", "amendment_sources", "amendment_tokens", "section_notes",
        "pending_change_sources", "diagnostics", "build_metadata")}
    supplements = []
    for record in sorted(manifest["documents"], key=lambda r: (r["kind"], r["source_url"])):
        url = record["source_url"]
        data = cache.get(url, record.get("sha256"))
        log(f"Parsing {url}")
        if record["kind"] == "chapter":
            number = str(record["chapter_number"])
            if not re.fullmatch(r"[1-9]\d{0,2}[A-Z]?", number):
                raise ValueError(f"invalid chapter number: {number}")
            parsed = parse_source(data, number, year, record.get("columns", 2))
            supplements.extend(parsed["identity"]["supplements"])
            tables["chapters"].append(dict(chapter_number=number, title=parsed["chapterName"], volume_number=record.get("volume_number"), edition_year=year))
            tables["chapter_sources"].append(dict(edition_year=year, chapter_number=number, source_url=url))

            def pending(text, section, ordinal):
                identity = digest(f"{year}:{number}:{section}:{ordinal}:{text}".encode())
                measure = re.search(r"(?:HB|SB)\s+\d+|\d{4}\s+c\.\s*\d+(?:\s+§\s*\w+)?|(?:sections?\s+[\d\w, and]+,\s*)?chapter\s+\d+,\s*Oregon Laws\s+\d{4}", text, re.I)
                tables["pending_changes"].append(dict(id=identity, target_section=section,
                    enacting_measure=measure[0] if measure else None, effective_date=explicit_effective_date(text), note_text=text))
                tables["pending_change_sources"].append(dict(pending_change_id=identity, edition_year=year, chapter_number=number, source_url=url))

            for section in parsed["sections"]:
                section_number = section["sectionNumber"]
                tables["sections"].append(dict(ors_section=section_number, chapter_number=number,
                    catchline=section["catchline"], content_text=section["bodyText"], edition_year=year))
                notes = [("editorial_note", n["text"]) for n in section["notes"]]
                if section["sourceCreditRaw"]:
                    notes.append(("source_credit", section["sourceCreditRaw"]))
                for ordinal, (kind, text) in enumerate(notes):
                    tables["section_notes"].append(dict(id=digest(f"{year}:{section_number}:{ordinal}".encode()),
                        edition_year=year, ors_section=section_number, note_kind=kind, note_text=text))
                    if kind != "source_credit" and re.search(r"amend|repeal|effective|takes effect|not added to ORS|becomes operative", text, re.I):
                        pending(text, section_number, ordinal)
            # General chapter notices do not identify individual target sections.
            notices = sorted({n["noticeText"] for n in parsed["pendingChangeNotices"]})
            for ordinal, text in enumerate(notices):
                pending(text, None, ordinal)
        else:
            if data.startswith(b"%PDF"):
                document = pdf_document(data, columns=record.get("columns", 2))
            else:
                markup, _ = decode_markup(data, declared_charset(data))
                document = html_document(markup)
            session = parse_session(document, url, record.get("session_year", year), record.get("special_session", 0))
            for action in session["actions"]:
                tables["amendments"].append({k: action[k] for k in ("id", "bill_number", "session_year", "affected_ors_section", "action_type", "raw_diff_text")})
                tables["amendment_sources"].append(dict(amendment_id=action["id"], source_url=url,
                    session_law_chapter=action["session_law_chapter"], session_law_section=action["session_law_section"], special_session=action["special_session"]))
                for token in action["tokens"]:
                    tables["amendment_tokens"].append(dict(amendment_id=action["id"], **token))
            for i, diagnostic in enumerate(session["diagnostics"]):
                tables["diagnostics"].append(dict(id=digest(f"{url}:{i}".encode()), source_url=url, **diagnostic))
    if not tables["chapters"]:
        raise ValueError("manifest contains no ORS chapters")
    tables["sources"] = sorted(cache.sources.values(), key=lambda r: r["source_url"])
    notes = {"scope": manifest.get("scope", "manifest"), "notes": manifest.get("notes"),
             "supplements": sorted({json.dumps(s, sort_keys=True) for s in supplements})}
    tables["editions"].append(dict(edition_year=year, effective_date=manifest.get("effective_date"),
        source_url=manifest.get("source_url") or manifest["documents"][0]["source_url"], notes=json.dumps(notes, sort_keys=True)))
    # Foreign keys require sources and edition rows before their dependents.
    ordered = {k: tables[k] for k in ("editions", "sources", "chapters", "sections", "amendments", "pending_changes",
        "chapter_sources", "amendment_sources", "amendment_tokens", "section_notes", "pending_change_sources", "diagnostics", "build_metadata")}
    for key, value in {"parser_version": __version__, "manifest": json.dumps(manifest, sort_keys=True),
                       "scope": manifest.get("scope", "manifest"), "review_required": str(bool(tables["diagnostics"])).lower()}.items():
        tables["build_metadata"].append(dict(key=key, value=value))
    write_sqlite(output, ordered)
    return {"edition_year": year, "scope": manifest.get("scope", "manifest"),
            "review_required": bool(tables["diagnostics"]), "row_counts": {k: len(v) for k, v in tables.items()}}
