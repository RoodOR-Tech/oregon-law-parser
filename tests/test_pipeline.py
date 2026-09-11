import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from parser.cache import Cache, digest
from parser.chapters import parse_source
from parser.cli import main
from parser.discovery import load_manifest
from parser.extract import html_document, pdf_document
from parser.identity import edition_identity
from parser.notes import split_bracket_notes
from parser.amendments import parse_session, token_stream
from parser.pipeline import build

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("banner", ["2023 EDITION", "2023\nEDITION", "Edition: 2023", "2023 ORS EDITION"])
def test_edition_metadata_and_supplements(banner):
    identity = edition_identity(banner + "\nAmended during the 2024 special session.", 2023)
    assert identity["edition_year"] == 2023
    assert identity["supplements"] == [{"session_year": 2024, "session_kind": "special", "special_session": 1}]


@pytest.mark.parametrize("text", ["[2023 c.1 §1]", "2021 EDITION", "2023 EDITION\n2025 EDITION"])
def test_reject_unproved_or_conflicting_editions(text):
    with pytest.raises(ValueError):
        edition_identity(text, 2023)


def test_brackets_end_at_closing_delimiter():
    body, notes = split_bracket_notes("Before [2024 c.12 §3 amends ORS 161.005 [with a nested note].] after [name].")
    assert body == "Before after [name]."
    assert len(notes) == 1
    with pytest.raises(ValueError, match="unterminated"):
        split_bracket_notes("[Series enacted into law but not added to ORS")


def test_chapter_notes_do_not_eat_body_or_next_section():
    result = parse_source((FIXTURES / "chapter.html").read_bytes(), "161", 2023)
    first, second = result["sections"]
    assert first["bodyText"] == "This is the primary statute. The following sentence remains statutory text."
    assert len(first["notes"]) == 2
    assert "[name]" in second["bodyText"] and "Note:" in second["bodyText"]


def test_styled_tokens_and_targets():
    doc = html_document((FIXTURES / "session.html").read_text())
    result = parse_session(doc, "fixture", 2023)
    assert [(a["action_type"], a["affected_ors_section"]) for a in result["actions"]] == [
        ("AMEND", "161.005"), ("REPEAL", "161.015"), ("REPEAL", "161.025"), ("ADD", None)]
    amendment = result["actions"][0]
    tokens = amendment["tokens"]
    assert [(t["operation"], t["text"]) for t in tokens if t["operation"] in ("ADD", "DELETE")] == [
        ("DELETE", "old"), ("ADD", "new"), ("ADD", "primary")]
    for token in tokens:
        assert amendment["raw_diff_text"][token["start"]:token["end"]] == token["text"]


def test_unbalanced_deletion_fails():
    with pytest.raises(ValueError):
        token_stream(html_document("<p>old [deleted <b>new</b></p>"))


def test_add_range_maps_actual_provision_bodies_and_skips_amendments():
    doc = html_document("""<p>OREGON LAWS 2023 Chap. 5</p><p>HB 1234</p>
        <p>SECTION 1. Sections 2 to 4 of this 2023 Act are added to and made a part of ORS chapter 161.</p>
        <p>SECTION 2. First new provision.</p>
        <p>SECTION 3. ORS 161.005 is amended to read:</p><p>161.005. Existing <b>new</b> text.</p>
        <p>SECTION 4. Second new provision.</p>""")
    result = parse_session(doc, "fixture", 2023)
    assert [(a["action_type"], a["session_law_section"]) for a in result["actions"]] == [
        ("ADD", "2"), ("ADD", "4"), ("AMEND", "3")]
    assert "First new provision" in result["actions"][0]["raw_diff_text"]
    assert not result["diagnostics"]


def test_special_sessions_do_not_collide_with_regular_actions():
    doc = html_document((FIXTURES / "session.html").read_text())
    regular = parse_session(doc, "fixture", 2023)
    special = parse_session(doc, "fixture", 2023, special_session=1)
    assert {a["id"] for a in regular["actions"]}.isdisjoint(a["id"] for a in special["actions"])


def test_cache_hash_verification_and_offline(tmp_path):
    source = tmp_path / "source.html"
    source.write_bytes(b"original")
    cache = Cache(tmp_path / "cache")
    url = source.as_uri()
    assert cache.get(url, digest(b"original")) == b"original"
    source.write_bytes(b"changed")
    assert Cache(cache.root, offline=True).get(url) == b"original"
    with pytest.raises(ValueError, match="hash mismatch"):
        Cache(cache.root, refresh=True).get(url, digest(b"original"))
    (cache.root / "objects" / digest(b"original")).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="corruption"):
        cache.get(url)
    with pytest.raises(ValueError, match="offline cache miss"):
        cache = Cache(tmp_path / "empty", offline=True)
        cache.get("https://example.invalid/law.pdf")


def test_database_idempotent_and_foreign_keys(tmp_path):
    manifest = load_manifest(FIXTURES / "manifest.json")
    db_path = tmp_path / "ors.db"
    cache = Cache(tmp_path / "cache")
    build(manifest, cache, db_path)
    first = db_path.read_bytes()
    manifest["documents"].reverse()
    # Canonical manifests must also ignore input ordering.
    build(manifest, Cache(cache.root, offline=True), db_path)
    with sqlite3.connect(db_path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT count(*) FROM sections").fetchone()[0] == 2
        assert db.execute("SELECT effective_date FROM pending_changes WHERE enacting_measure IS NOT NULL").fetchone()[0] == "2025-01-01"
        assert db.execute("SELECT count(*) FROM amendments").fetchone()[0] == 4
        assert db.execute("SELECT effective_date FROM editions").fetchone()[0] is None
    assert db_path.read_bytes() == first


def test_failed_build_preserves_existing_output(tmp_path):
    output = tmp_path / "ors.db"
    output.write_bytes(b"keep existing database")
    manifest = load_manifest(FIXTURES / "manifest.json")
    manifest["edition_year"] = 2025
    with pytest.raises(ValueError, match="edition mismatch"):
        build(manifest, Cache(tmp_path / "cache"), output)
    assert output.read_bytes() == b"keep existing database"


def test_cli_and_parquet_roundtrip(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    assert main(["run", "--year", "2023", "--manifest", str(FIXTURES / "manifest.json"),
        "--output", str(tmp_path / "ors.db"), "--cache", str(tmp_path / "cache"),
        "--parquet-dir", str(tmp_path / "parquet"), "--quiet"]) == 0
    with duckdb.connect() as db:
        assert db.execute("SELECT count(*) FROM read_parquet(?)", [str(tmp_path / "parquet" / "sections.parquet")]).fetchone()[0] == 2


def test_bundled_real_session_pdf():
    doc = pdf_document((ROOT / "fixtures/2022orlaw0002.pdf").read_bytes())
    result = parse_session(doc, "2022orlaw0002.pdf", 2022)
    assert [a["affected_ors_section"] for a in result["actions"]] == ["285B.746", "285B.749", "285B.753"]
    assert result["bill_number"] == "HB 4015"
    # Earlier act-section amendments mention ORS but must not duplicate actions.
    assert len(result["diagnostics"]) >= 2
    assert any(t["operation"] == "DELETE" for a in result["actions"] for t in a["tokens"])


def test_bundled_non_ors_amendment_is_not_misfiled():
    doc = pdf_document((ROOT / "fixtures/2022orlaw0001.pdf").read_bytes())
    result = parse_session(doc, "2022orlaw0001.pdf", 2022)
    assert result["actions"] == []
    assert result["diagnostics"][0]["clause"] == "1"
