"""Export an offline-capable static working surface from the relational data."""
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from collections import defaultdict
from contextlib import closing


def export_explorer(database, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    def save(name, value):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        def rows(sql, params=()):
            return [dict(r) for r in db.execute(sql, params)]
        years = rows('SELECT * FROM editions ORDER BY edition_year')
        if len(years) != 1:
            raise ValueError('Explorer export requires one edition per database')
        index, postings = [], defaultdict(list)
        def grouped(sql, key):
            groups = defaultdict(list)
            for row in rows(sql):
                groups[row[key]].append(row)
            return groups
        all_versions = grouped('SELECT * FROM section_versions ORDER BY edition_year,ors_section,version_ordinal', 'ors_section')
        all_notes = grouped('SELECT ors_section,note_kind,note_text FROM section_notes ORDER BY id', 'ors_section')
        all_pending = grouped('SELECT * FROM pending_changes ORDER BY id', 'target_section')
        chapter_pending = grouped('SELECT p.*,s.chapter_number FROM pending_changes p JOIN pending_change_sources s ON s.pending_change_id=p.id WHERE p.target_section IS NULL ORDER BY p.id', 'chapter_number')
        all_sections = grouped('SELECT * FROM sections ORDER BY ors_section', 'chapter_number')
        chapters = rows('SELECT c.*, s.source_url FROM chapters c JOIN chapter_sources s USING(edition_year,chapter_number) ORDER BY CAST(chapter_number AS INTEGER),chapter_number')
        for chapter in chapters:
            number = chapter['chapter_number']
            sections = all_sections[number]
            detail = {}
            for section in sections:
                key = section['ors_section']
                versions = all_versions[key]
                ordinal = len(index)
                index.append([key, number, section['catchline'], versions[0]['status'], len(versions)])
                words = set(re.findall(r'[a-z0-9]+', ' '.join([key, section['catchline'] or ''] + [v['content_text'] or '' for v in versions]).lower()))
                for word in words:
                    postings[word].append(ordinal)
                detail[key] = dict(versions=versions, notes=all_notes[key], pending=all_pending[key])
            chapter['section_count'] = len(sections)
            save(f'data/chapters/{number}.json', dict(sections=detail, notes=rows('SELECT note_text FROM chapter_notes WHERE chapter_number=? ORDER BY id', (number,)), pending=chapter_pending[number]))
        shards = defaultdict(dict)
        for word, hits in sorted(postings.items()):
            shards[word[:2]][word] = hits
        for prefix, words in shards.items():
            save(f'data/search/{prefix}.json', words)
        save('data/index.json', index)
        actions = rows('SELECT a.*,s.source_url,s.session_law_chapter,s.session_law_section,s.special_session,c.condition_text,c.operative_text FROM amendments a JOIN amendment_sources s ON s.amendment_id=a.id JOIN amendment_context c ON c.amendment_id=a.id ORDER BY a.session_year,s.session_law_chapter,s.session_law_section,a.id')
        summaries = []
        for a in actions:
            summaries.append({k:v for k,v in a.items() if k not in ('raw_diff_text','operative_text')})
            a['tokens'] = rows("SELECT operation,start,end FROM amendment_tokens WHERE amendment_id=? AND operation IN ('ADD','DELETE','MARKER') ORDER BY ordinal", (a['id'],))
            save(f"data/actions/{a['id']}.json", a)
        save('data/actions.json', summaries)
        reviews = rows('SELECT d.*,r.category,r.disposition,r.explanation FROM diagnostics d JOIN diagnostic_reviews r ON r.diagnostic_id=d.id ORDER BY d.source_url,d.clause')
        save('data/reviews.json', reviews)
        checksum = hashlib.sha256()
        with open(database, 'rb') as stream:
            for block in iter(lambda: stream.read(1024*1024), b''):
                checksum.update(block)
        save('data/catalog.json', dict(edition=years[0], chapters=chapters, sections=len(index), amendments=len(actions), diagnostics=len(reviews), unresolved=sum(r['disposition']=='review_required' for r in reviews), search_shards=sorted(shards), database_sha256=checksum.hexdigest()))
    for asset in (Path(__file__).parent/'web').iterdir():
        (output/asset.name).write_text(asset.read_text(encoding='utf-8').replace('2023', str(years[0]['edition_year'])), encoding='utf-8')
    return dict(output=str(output), sections=len(index), amendments=len(actions))
