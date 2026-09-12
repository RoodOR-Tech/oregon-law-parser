"""Boundary and replay regressions found during the statewide build."""
import json
from pathlib import Path
import sqlite3

import pytest

from parser.amendments import parse_session, token_stream
from parser.cache import Cache, digest
from parser.chapters import parse_source
from parser.cli import main
from parser.discovery import load_manifest, pin_manifest
from parser.extract import html_document, reading_regions
from parser.identity import edition_identity
from parser.pipeline import build

FIXTURES = Path(__file__).parent / 'fixtures'


def test_inline_style_changes_preserve_unchanged_spelling():
    doc = html_document('<p>un<b>law</b>ful [<b>old</b>] <u>new</u></p>')
    tokens = token_stream(doc)
    assert [(t['text'], t['operation']) for t in tokens] == [
        ('un', 'KEEP'), ('law', 'ADD'), ('ful', 'KEEP'), ('[', 'MARKER'),
        ('old', 'DELETE'), (']', 'MARKER'), ('new', 'ADD')]
    assert all(doc.text[t['start']:t['end']] == t['text'] for t in tokens)


@pytest.mark.parametrize('ordinal,number', [('first', 1), ('second', 2), ('3rd', 3)])
def test_printed_special_session_identity(ordinal, number):
    doc = html_document(f'<p>Chapter 2 Oregon Laws 2023 {ordinal} special session</p>'
                        '<p>HB 1001</p><p>SECTION 1. ORS 71.1010 is amended to read:</p>'
                        '<p>71.1010. <b>New</b> text.</p>')
    result = parse_session(doc, 'fixture', 2023)
    assert result['actions'][0]['special_session'] == number
    with pytest.raises(ValueError, match='conflicting special-session'):
        parse_session(doc, 'fixture', 2023, 0)
    assert edition_identity(f'2023 EDITION\n2024 {ordinal} special session')['supplements'][0]['special_session'] == number


def test_pending_bracket_at_end_is_not_a_source_credit():
    data = ('<p>Chapter 161 - General Provisions</p><p>2023 EDITION</p>'
            '<p><b>161.005 Short title.</b> Statute [name]. '
            '[2024 c.12 §3 amends ORS 161.005 effective January 1, 2025.]</p>').encode()
    section = parse_source(data, '161', 2023)['sections'][0]
    assert section['bodyText'] == 'Statute [name].'
    assert section['sourceCreditRaw'] is None
    assert '2024 c.12' in section['notes'][0]['text']


def test_terminal_form_placeholder_is_not_history():
    data = b'<p>Chapter 161 - General</p><p>2023 EDITION</p><p><b>161.005 Form.</b> Sign [name]</p>'
    assert parse_source(data, '161', 2023)['sections'][0]['bodyText'] == 'Sign [name]'


def test_repeated_versions_survive_relational_export(tmp_path):
    data = ('<p>Chapter 161 - General</p><p>2023 EDITION</p>'
            '<p><b>161.005 New catchline.</b> Future version. [2023 c.1 §1]</p>'
            '<p><b>Note:</b> Amendments become operative January 1, 2025. The previous version follows.</p>'
            '<p><b>161.005 Old catchline.</b> Earlier version.</p>')
    path = tmp_path / 'chapter.html'
    path.write_text(data, encoding='utf-8')
    manifest = dict(schema_version=1, edition_year=2023,
                    documents=[dict(kind='chapter', chapter_number='161', source_url=path.as_uri())])
    output = tmp_path / 'ors.db'
    build(manifest, Cache(tmp_path/'cache'), output)
    with sqlite3.connect(output) as db:
        assert db.execute('SELECT content_text FROM sections').fetchone()[0] == 'Future version.'
        assert db.execute('SELECT content_text FROM section_versions ORDER BY version_ordinal').fetchall() == [('Future version.',), ('Earlier version.',)]
        assert db.execute('SELECT count(*) FROM pending_changes').fetchone()[0] == 1


def test_operative_targets_do_not_include_incidental_citations():
    doc = html_document('<p>OREGON LAWS 2023 Chap. 1</p><p>HB 1001</p>'
                        '<p>SECTION 1. Repeals. ORS 71.1010 and 71.2010 are repealed.</p>'
                        '<p>SECTION 2. ORS 161.005 is amended to read:</p>'
                        '<p>161.005. Body.</p><p>NOTE: This is an editorial explanation.</p>')
    actions = parse_session(doc, 'fixture', 2023)['actions']
    assert [a['affected_ors_section'] for a in actions] == ['71.1010', '71.2010', '161.005']
    assert 'NOTE:' not in actions[-1]['raw_diff_text']


def test_manifest_rejects_duplicate_chapter_and_bad_columns(tmp_path):
    manifest = load_manifest(FIXTURES/'manifest.json')
    manifest['documents'].append(dict(manifest['documents'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        pin_manifest(manifest, Cache(tmp_path/'cache'))
    manifest['documents'].pop()
    manifest['documents'][0]['columns'] = 3
    with pytest.raises(ValueError, match='columns'):
        pin_manifest(manifest, Cache(tmp_path/'cache'))


def test_manifest_pins_previously_unpinned_local_sources(tmp_path):
    manifest = load_manifest(FIXTURES/'manifest.json')
    pinned = pin_manifest(manifest, Cache(tmp_path/'cache'))
    assert all(len(r['sha256']) == 64 for r in pinned['documents'])
    assert all('sha256' not in r for r in manifest['documents'])


def test_refresh_once_per_run_and_literal_percent_filename(tmp_path):
    source = tmp_path/'law%20name.html'
    source.write_bytes(b'original')
    cache = Cache(tmp_path/'cache', refresh=True)
    assert cache.get(source.as_uri()) == b'original'
    source.write_bytes(b'changed')
    assert cache.get(source.as_uri()) == b'original'
    assert Cache(cache.root, refresh=True).get(source.as_uri()) == b'changed'
    assert Cache(cache.root, offline=True).get(source.as_uri(), digest(b'original')) == b'original'


def test_failed_cli_keeps_published_manifest(tmp_path):
    out = tmp_path/'ors.db'
    out.write_bytes(b'existing')
    published = out.with_suffix('.manifest.json')
    published.write_bytes(b'existing manifest')
    chapter = tmp_path/'chapter.html'
    chapter.write_text('<p>2021 EDITION</p>')
    manifest = tmp_path/'input.json'
    manifest.write_text(json.dumps(dict(schema_version=1, edition_year=2023,
        documents=[dict(kind='chapter', chapter_number='1', path='chapter.html')])))
    assert main(['run','--year','2023','--manifest',str(manifest),'--output',str(out),
                 '--cache',str(tmp_path/'cache'),'--quiet']) == 1
    assert out.read_bytes() == b'existing'
    assert published.read_bytes() == b'existing manifest'
    assert out.with_suffix('.acquired.json').exists()


def test_mixed_column_form_reading_order():
    def glyphs(text, x, y, width=3):
        return [dict(text=c, x0=x+i*width, x1=x+(i+1)*width, top=y, bottom=y+8)
                for i,c in enumerate(text)]
    chars = (glyphs('left1',0,10)+glyphs('left2',0,20)+glyphs('right1',60,10)
             +glyphs('right2',60,20)+glyphs('_'*32,0,30)
             +glyphs('Full width form text across gutter',0,45))
    regions = reading_regions(chars, 50)
    assert [''.join(c['text'] for c in r) for r in regions] == [
        'left1left2','right1right2','_'*32,'Full width form text across gutter']


def test_indexed_deduplication_matches_pdfplumber():
    import pdfplumber
    from parser.extract import deduplicate_chars
    with pdfplumber.open(FIXTURES.parents[1]/'fixtures/2022orlaw0002.pdf') as pdf:
        for page in pdf.pages:
            assert deduplicate_chars(page.chars) == page.dedupe_chars().chars
    chars = [dict(upright=True, text='a', fontname='Roman', size=10,
                  doctop=y, x0=x) for x,y in [(1,1),(1.4,1),(8,1),(8,1),(15,12)]]
    assert deduplicate_chars(chars) == pdfplumber.utils.dedupe_chars(chars)


def test_bare_alternate_version_is_retained():
    data = ('<p>Chapter 161 - General</p><p>2023 EDITION</p>'
            '<p><b>161.005 Caption.</b> Main text. [2023 c.1 §1]</p>'
            '<p><b>Note:</b> Prior text follows.</p><p><b>161.005.</b> Prior body.</p>').encode()
    parsed = parse_source(data,'161',2023)
    assert [s['bodyText'] for s in parsed['sections']] == ['Main text.','Prior body.']


@pytest.mark.parametrize('subject', ['Sections 2 and 3', 'Sections 2 and 3 of this 2023 Act and ORS 192.695'])
def test_add_membership_maps_new_bodies_without_inventing_existing_adds(subject):
    doc=html_document(f'<p>OREGON LAWS 2023 Chap. 1</p><p>HB 1001</p>'
        f'<p>SECTION 1. {subject} are added to and made a part of ORS chapter 192.</p>'
        '<p>SECTION 2. New provision.</p><p>SECTION 3. ORS 192.610 does not apply to this new provision.</p>')
    result=parse_session(doc,'fixture',2023)
    assert [a['session_law_section'] for a in result['actions']]==['2','3']
    assert all(a['affected_ors_section'] is None for a in result['actions'])


def test_existing_series_membership_is_not_new_enacted_text():
    doc=html_document('<p>OREGON LAWS 2023 Chap. 1</p><p>HB 1001</p>'
        '<p>SECTION 1. ORS 414.638 is added to and made a part of ORS chapter 413.</p>')
    result=parse_session(doc,'fixture',2023)
    assert result['actions']==[]
    assert result['diagnostics'][0]['reason']=='existing ORS series membership'
