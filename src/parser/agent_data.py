"""Read-only, versioned agent queries over an indexed publication snapshot."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any

NOTICE = 'Printed publication data, not a current-law consolidation. Amendments and pending notes do not establish current applicability.'


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def prepare(source, output):
    """Atomically build a separate indexed snapshot; never mutate the source."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError('Source and serving database must be different files')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=output.parent, suffix='.sqlite3')
    os.close(fd)
    try:
        with closing(connect(source)) as original, closing(sqlite3.connect(temporary)) as db:
            original.backup(db)
            db.executescript('''
                DROP TABLE IF EXISTS agent_fts;
                DROP TABLE IF EXISTS agent_metadata;
                CREATE VIRTUAL TABLE agent_fts USING fts5(ors_section UNINDEXED,
                    edition_year UNINDEXED, chapter_number UNINDEXED, version_ordinal UNINDEXED,
                    status UNINDEXED, catchline, content_text, tokenize='unicode61');
                INSERT INTO agent_fts SELECT s.ors_section,s.edition_year,s.chapter_number,
                    v.version_ordinal,v.status,v.catchline,v.content_text
                    FROM sections s JOIN section_versions v USING(edition_year,ors_section);
                CREATE TABLE agent_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS agent_notes ON section_notes(edition_year,ors_section);
                CREATE INDEX IF NOT EXISTS agent_chapters ON sections(edition_year,chapter_number,ors_section);
                INSERT INTO agent_fts(agent_fts) VALUES('optimize');
                ANALYZE;
            ''')
            digest = hashlib.sha256()
            with open(temporary, 'rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            metadata = {'snapshot_id': digest.hexdigest(), 'api_version': '1',
                        'notice': NOTICE, 'index_version': '1'}
            db.executemany('INSERT INTO agent_metadata VALUES(?,?)', metadata.items())
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Serving database integrity check failed')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return metadata


def normalize_citation(value):
    match = re.fullmatch(r'(?:ORS\s+)?([1-9]\d{0,2}[A-Z]?\.\d{3,4})', value.strip().upper())
    if not match:
        raise ValueError('Use an ORS citation such as 90.100 or 646A.602')
    return match[1]


def pagination(limit, offset):
    if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
        raise ValueError('limit must be 1–100; offset must be 0–100000')


class AgentData:
    def __init__(self, database):
        self.database = Path(database).resolve()
        with closing(connect(self.database)) as db:
            self.metadata = dict(db.execute('SELECT key,value FROM agent_metadata'))
        if self.metadata.get('index_version') != '1':
            raise ValueError('Rebuild the serving index using prepare')

    def _response(self, **values):
        return dict(api_version='1', snapshot_id=self.metadata['snapshot_id'], notice=NOTICE, **values)

    def _page(self, rows, limit, offset):
        return self._response(items=[dict(r) for r in rows[:limit]], limit=limit,
                              offset=offset, next_offset=offset+limit if len(rows)>limit else None)

    def get_dataset_info(self) -> dict[str, Any]:
        """Read coverage and provenance before interpreting publication text."""
        with closing(connect(self.database)) as db:
            editions = [dict(r) for r in db.execute('SELECT * FROM editions ORDER BY edition_year')]
            counts = {t:db.execute('SELECT count(*) FROM '+t).fetchone()[0]
                      for t in ('chapters','sections','section_versions','amendments','pending_changes','diagnostics')}
            sessions = [r[0] for r in db.execute('SELECT DISTINCT session_year FROM amendments ORDER BY session_year')]
            build = dict(db.execute('SELECT key,value FROM build_metadata'))
            manifest = build.pop('manifest',None)
            if manifest is not None:
                build['manifest_sha256'] = hashlib.sha256(manifest.encode('utf-8')).hexdigest()
            reviews = [dict(r) for r in db.execute('SELECT disposition,count(*) AS count FROM diagnostic_reviews GROUP BY disposition ORDER BY disposition')]
        return self._response(editions=editions, counts=counts, session_years=sessions,
                              build_metadata=build, diagnostic_reviews=reviews, search_semantics='All words; BM25 across printed versions; exact citation lookup',
                              limits={'max_page_size':100,'max_query_length':300})

    def search_sections(self, query: str, edition: int | None = None, chapter: str | None = None,
                        limit: int = 10, offset: int = 0) -> dict[str, Any]:
        """Search printed versions; return short excerpts and source URLs. All query words must match."""
        pagination(limit, offset)
        if not query.strip() or len(query)>300:
            raise ValueError('query must contain 1–300 characters')
        filters, args = [], []
        if edition is not None:
            filters.append('f.edition_year=?'); args.append(edition)
        if chapter is not None:
            chapter=chapter.strip().upper()
            if not re.fullmatch(r'[1-9]\d{0,2}[A-Z]?',chapter):
                raise ValueError('Invalid chapter')
            filters.append('f.chapter_number=?'); args.append(chapter)
        try:
            exact = normalize_citation(query)
        except ValueError:
            exact = None
        if exact:
            filters.insert(0,'f.ors_section=?'); args.insert(0,exact)
            excerpt, rank = 'substr(f.content_text,1,400)', '0.0'
        else:
            words = re.findall(r'\w+',query,flags=re.UNICODE)
            if not words:
                raise ValueError('query must contain a word or citation')
            filters.insert(0,'agent_fts MATCH ?'); args.insert(0,' AND '.join('"'+w+'"' for w in words))
            excerpt, rank = "snippet(agent_fts,6,'[',']',' … ',48)", 'bm25(agent_fts,0,0,0,0,0,5,1)'
        sql = f'''SELECT f.ors_section, f.edition_year,f.chapter_number,f.version_ordinal,f.status,
            f.catchline,{excerpt} AS excerpt,{rank} AS rank,c.source_url,
            'ors:'||f.edition_year||':'||f.ors_section||':v'||f.version_ordinal AS id
            FROM agent_fts f LEFT JOIN chapter_sources c ON c.edition_year=f.edition_year AND c.chapter_number=f.chapter_number
            WHERE {' AND '.join(filters)} ORDER BY rank,f.edition_year DESC,f.ors_section,f.version_ordinal LIMIT ? OFFSET ?'''
        with closing(connect(self.database)) as db:
            rows = db.execute(sql,args+[limit+1,offset]).fetchall()
        return self._page(rows,limit,offset)

    def get_section(self, citation: str, edition: int) -> dict[str, Any]:
        """Get a cited section in an explicit edition, including all printed versions and source evidence."""
        number = normalize_citation(citation)
        with closing(connect(self.database)) as db:
            section = db.execute('SELECT * FROM sections WHERE ors_section=? AND edition_year=?',(number,edition)).fetchone()
            if section is None:
                raise LookupError('Section not found in this edition')
            versions = [dict(r) for r in db.execute('SELECT * FROM section_versions WHERE ors_section=? AND edition_year=? ORDER BY version_ordinal',(number,edition))]
            notes = [dict(r) for r in db.execute('SELECT * FROM section_notes WHERE ors_section=? AND edition_year=? ORDER BY id',(number,edition))]
            sources = [dict(r) for r in db.execute('SELECT s.* FROM chapter_sources c JOIN sources s USING(source_url) WHERE c.edition_year=? AND c.chapter_number=?',(edition,section['chapter_number']))]
        return self._response(id=f'ors:{edition}:{number}',section=dict(section),versions=versions,notes=notes,sources=sources)

    def get_amendments(self, citation: str, session_year: int | None = None, limit: int = 10, offset: int = 0, include_text: bool = False) -> dict[str, Any]:
        """Get action excerpts and provenance; set include_text for full diffs. Not consolidated law."""
        pagination(limit,offset)
        where, args = 'a.affected_ors_section=?',[normalize_citation(citation)]
        if session_year is not None:
            where+=' AND a.session_year=?';args.append(session_year)
        with closing(connect(self.database)) as db:
            rows=db.execute('''SELECT a.id,a.bill_number,a.session_year,a.affected_ors_section,a.action_type,
                CASE WHEN ? THEN a.raw_diff_text ELSE substr(a.raw_diff_text,1,500) END AS raw_diff_text,
                length(a.raw_diff_text)>500 AND NOT ? AS text_truncated,
                s.source_url,s.session_law_chapter,s.session_law_section,s.special_session,
                c.condition_text,CASE WHEN ? THEN c.operative_text ELSE NULL END AS operative_text
                FROM amendments a LEFT JOIN amendment_sources s ON a.id=s.amendment_id
                LEFT JOIN amendment_context c ON a.id=c.amendment_id WHERE '''+where+
                ' ORDER BY a.session_year,a.id LIMIT ? OFFSET ?',[include_text]*3+args+[limit+1,offset]).fetchall()
        return self._page(rows,limit,offset)

    def get_pending_changes(self, citation: str, edition: int | None = None, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        """Get recorded pending notes with source edition; null dates mean unknown, not effective now."""
        pagination(limit,offset)
        where,args='p.target_section=?',[normalize_citation(citation)]
        if edition is not None:
            where+=' AND s.edition_year=?';args.append(edition)
        with closing(connect(self.database)) as db:
            rows=db.execute('''SELECT p.*,s.edition_year,s.source_url FROM pending_changes p
                LEFT JOIN pending_change_sources s ON p.id=s.pending_change_id WHERE '''+where+
                ' ORDER BY p.effective_date,p.id LIMIT ? OFFSET ?',args+[limit+1,offset]).fetchall()
        return self._page(rows,limit,offset)
