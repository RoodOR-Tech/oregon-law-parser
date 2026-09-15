"""Build and audit the synonym layer without importing the ORS parser."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from contextlib import closing

from sqlalchemy import func, select
from search import build_synonym_db as upstream
from search.browser_runtime import verify_runtime


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def export_source_rows(database, output):
    """Project the Explorer's SQLite input to the existing upstream rows adapter."""
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        if db.execute('SELECT count(*) FROM editions').fetchone()[0] != 1:
            raise ValueError('Use a single-edition database')
        rows = [dict(sectionNumber=n, catchline=t, bodyText=b, status=s) for n,t,b,s in db.execute(
            'SELECT ors_section,catchline,content_text,status FROM section_versions WHERE version_ordinal=0 ORDER BY ors_section')]
    Path(output).write_text(json.dumps({'sections':rows}, ensure_ascii=False), encoding='utf-8')
    return upstream.load_statute_chunks_from_ors_rows(Path(output))


def validate_payload(raw):
    match = upstream._JSON_FENCE_PATTERN.search(raw)
    payload = json.loads(match.group('body') if match else raw)
    if not isinstance(payload, dict) or set(payload) != {'layperson_questions','colloquial_synonyms','legal_terms_of_art'}:
        raise ValueError('Unexpected expansion JSON shape')
    def strings(value):
        return isinstance(value, list) and all(isinstance(s,str) and s.strip() for s in value)
    if not strings(payload['layperson_questions']) or not 3 <= len(payload['layperson_questions']) <= 5:
        raise ValueError('Expected 3–5 nonempty questions')
    if not strings(payload['legal_terms_of_art']):
        raise ValueError('Expected a list of terms')
    synonyms = payload['colloquial_synonyms']
    if not isinstance(synonyms,dict) or not synonyms or not all(isinstance(k,str) and k.strip() and strings(v) and v for k,v in synonyms.items()):
        raise ValueError('Expected nonempty term-to-phrases mappings')
    return payload


class AuditedClient(upstream.LLMClient):
    def __init__(self, client, directory):
        self.client, self.directory, self.records = client, Path(directory), {}
        self.directory.mkdir(parents=True, exist_ok=True)

    async def complete(self, prompt):
        citation = re.search(r'^ORS Citation:\s*(\S+)', prompt, re.M)[1]
        if not re.fullmatch(r'\d{1,3}[A-Z]?\.\d{3,4}',citation):
            raise ValueError('Invalid citation for audit file')
        raw = await self.client.complete(prompt)
        record = dict(citation=citation,prompt=prompt,raw_response=raw,
                      prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                      response_sha256=hashlib.sha256(raw.encode()).hexdigest())
        # Even malformed/truncated output must be retained for real review.
        path = self.directory/(citation+'.json')
        try:
            record['payload'] = validate_payload(raw)
            record['json_valid'] = True
        except (ValueError,TypeError) as exc:
            record['json_valid'] = False
            record['validation_error'] = str(exc)
            path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            raise
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        self.records[citation] = dict(audit_file=path.name,sha256=checksum(path))
        return raw


def literal_definition_keys(engine):
    """Make definitions searchable; upstream query expansion reads synonym rows."""
    with upstream.get_session_factory(engine)() as session:
        existing = set(session.execute(select(upstream.SynonymKey.statute_id,upstream.SynonymKey.canonical_term,upstream.SynonymKey.layperson_synonym)).all())
        for definition in session.scalars(select(upstream.Definition).order_by(upstream.Definition.id)):
            key = (definition.statute_id,definition.defined_term,definition.defined_term)
            if key not in existing:
                session.add(upstream.SynonymKey(statute_id=key[0],canonical_term=key[1],layperson_synonym=key[2],query_context='definition'))
                existing.add(key)
        session.commit()


async def build_layer(source, output, provider='none', model=None, citations=(), base_database=None):
    output = Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():
        raise ValueError('Use a new database output path; preserve the previous reviewed build')
    rows_path = output.with_suffix('.rows.json')
    chunks = export_source_rows(source, rows_path)
    if provider != 'none' and (not model or not citations):
        raise ValueError('Real expansion requires an explicit model and bounded citation list')
    selected = [c for c in chunks if c.citation in citations]
    if set(c.citation for c in selected) != set(citations):
        raise ValueError('Requested LLM citation missing from operative printed-version rows')
    if base_database:
        base_database=Path(base_database)
        baseline=json.loads(base_database.with_suffix('.build.json').read_text(encoding='utf-8'))
        if baseline['provider']!='none' or baseline['source_database_sha256']!=checksum(source) or baseline['database_sha256']!=checksum(base_database) or baseline['module_sha256']!=checksum(Path(upstream.__file__)):
            raise ValueError('Baseline must be an unchanged definitions-only build of these sources and this module')
        shutil.copyfile(base_database,output)
    engine = upstream.get_engine('sqlite:///'+str(output.resolve()))
    records = {}
    try:
        if not base_database:
            await upstream.build_database(chunks,engine,llm_client=None)
        if provider != 'none':
            client = upstream._build_llm_client(provider,model)
            audited = AuditedClient(client,output.with_suffix('.audit'))
            try:
                await upstream.build_database(selected,engine,llm_client=audited,concurrency=1)
            finally:
                await client._client.close()
            if set(audited.records) != set(citations):
                raise ValueError('Not all real-provider expansions passed JSON validation; inspect audit files')
            records = audited.records
        literal_definition_keys(engine)
        with upstream.get_session_factory(engine)() as session:
            counts = {table.__tablename__:session.scalar(select(func.count()).select_from(table)) for table in (upstream.Statute,upstream.Definition,upstream.SynonymKey)}
            if counts['statutes'] != len(chunks):
                raise ValueError('Upstream ingestion skipped one or more statutes')
    finally:
        engine.dispose()
    report = dict(schema_version=1,source_database_sha256=checksum(source),database_sha256=checksum(output),
                  module_sha256=checksum(Path(upstream.__file__)),provider=provider,model=model,
                  llm_citations=sorted(citations),llm_responses=records,counts=counts,
                  manually_reviewed=False,review_note=None)
    output.with_suffix('.build.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def export_bundle(database, explorer, runtime):
    """Fail closed until every real response has been manually reviewed."""
    database,explorer,runtime = Path(database),Path(explorer),Path(runtime)
    report = json.loads(database.with_suffix('.build.json').read_text(encoding='utf-8'))
    if report['provider'] not in ('openai','anthropic') or not report['manually_reviewed'] or not report.get('review_note'):
        raise ValueError('Real LLM responses must be manually reviewed before enabling hybrid search')
    if checksum(database)!=report['database_sha256'] or checksum(Path(upstream.__file__))!=report['module_sha256']:
        raise ValueError('Database or module changed since review')
    if not report['llm_citations'] or set(report['llm_responses'])!=set(report['llm_citations']):
        raise ValueError('Incomplete real-provider audit')
    for item in report['llm_responses'].values():
        if checksum(database.with_suffix('.audit')/item['audit_file']) != item['sha256']:
            raise ValueError('LLM audit changed since review')
    catalog_path = explorer/'data/catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    if catalog['database_sha256'] != report['source_database_sha256']:
        raise ValueError('Synonym layer and Explorer were built from different sources')
    verify_runtime(runtime)
    target = explorer/'hybrid'
    target.mkdir(exist_ok=True)
    shutil.copyfile(database,target/'synonyms.sqlite3')
    # Query-time expansion never reads statutory body text. Keep the complete
    # source database separately and publish a compact, clearly marked copy.
    with closing(sqlite3.connect(target/'synonyms.sqlite3')) as db:
        db.execute("UPDATE statutes SET text_content=''")
        db.commit()
        db.execute('VACUUM')
    shutil.copyfile(upstream.__file__,target/'build_synonym_db.py')
    shutil.copytree(runtime,target/'runtime',dirs_exist_ok=True)
    catalog['hybrid'] = dict(enabled=True,provider=report['provider'],model=report['model'],
        llm_citations=report['llm_citations'],counts=report['counts'],query_database_sha256=checksum(target/'synonyms.sqlite3'))
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return catalog['hybrid']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    commands=p.add_subparsers(dest='command',required=True)
    build=commands.add_parser('build')
    build.add_argument('--ors-db',type=Path,required=True)
    build.add_argument('--output',type=Path,required=True)
    build.add_argument('--llm-provider',choices=['none','openai','anthropic'],default='none')
    build.add_argument('--llm-model')
    build.add_argument('--llm-citations',default='')
    build.add_argument('--base-db',type=Path,help='Reuse a verified definitions-only build without reingesting the corpus')
    export=commands.add_parser('export')
    export.add_argument('--database',type=Path,required=True)
    export.add_argument('--explorer',type=Path,required=True)
    export.add_argument('--runtime',type=Path,required=True)
    args=p.parse_args()
    if args.command=='build':
        result=asyncio.run(build_layer(args.ors_db,args.output,args.llm_provider,args.llm_model,[c.strip() for c in args.llm_citations.split(',') if c.strip()],args.base_db))
    else:
        result=export_bundle(args.database,args.explorer,args.runtime)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
