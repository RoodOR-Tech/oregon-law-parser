import hashlib
import json
from pathlib import Path

from parser.cache import Cache
from parser.discovery import load_manifest
from parser.explorer import export_explorer
from parser.pipeline import build


def test_export_search_and_evidence_are_grounded_in_database(tmp_path):
    manifest = load_manifest(Path(__file__).parent/'fixtures/manifest.json')
    database = tmp_path/'source.db'
    build(manifest, Cache(tmp_path/'cache'), database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    output = tmp_path/'site'
    report = export_explorer(database, output)
    def read(name):
        return json.loads((output/'data'/f'{name}.json').read_text(encoding='utf-8'))
    catalog, index, actions = read('catalog'), read('index'), read('actions')
    assert catalog['database_sha256'] == before == hashlib.sha256(database.read_bytes()).hexdigest()
    assert len(index) == report['sections'] > 0
    assert len(actions) == report['amendments'] > 0
    for n, chapter, title, status, count in index:
        section = read(f'chapters/{chapter}')['sections'][n]
        assert len(section['versions']) == count
        assert section['versions'][0]['status'] == status
    for prefix in catalog['search_shards']:
        for word, ids in read(f'search/{prefix}').items():
            assert word.startswith(prefix)
            assert ids == sorted(set(ids))
            assert all(0 <= i < len(index) for i in ids)
    for action in actions:
        detail = read(f"actions/{action['id']}")
        assert detail['source_url'] == action['source_url']
        assert all(0 <= t['start'] < t['end'] <= len(detail['raw_diff_text']) for t in detail['tokens'])
    assert (output/'index.html').is_file()
    assert (output/'app.js').is_file()
