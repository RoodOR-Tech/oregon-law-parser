"""Exercise the upstream schema in an isolated, disposable PostgreSQL schema."""
import argparse
import json
import os
from pathlib import Path
import uuid

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine, make_url

from search.build_synonym_db import (
    Definition, QueryExpansion, Statute, SynonymKey, extract_definitions,
    expand_user_query, get_engine, get_session_factory, ingest_statute,
    load_statute_chunks_from_ors_rows,
)


def verify(url, rows_file):
    parsed = make_url(url)
    if parsed.get_backend_name() != 'postgresql':
        raise ValueError('A real PostgreSQL URL is required')
    parsed = parsed.set(drivername='postgresql+psycopg2')
    schema = 'ors_search_probe_' + uuid.uuid4().hex
    control = create_engine(parsed, connect_args={'connect_timeout': 15})
    engine = None
    created = False
    try:
        with control.begin() as conn:
            version = conn.execute(text('SHOW server_version')).scalar_one()
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        # Set search_path with SQL, not a startup option rejected by some
        # PostgreSQL proxies. The listener exists only during this probe.
        def select_schema(connection, _):
            previous = connection.autocommit
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET search_path TO "{schema}"')
            finally:
                connection.autocommit = previous
        event.listen(Engine, 'connect', select_schema)
        try:
            engine = get_engine(parsed.update_query_dict({'connect_timeout':'15'}))
        finally:
            event.remove(Engine, 'connect', select_schema)
        chunks = load_statute_chunks_from_ors_rows(rows_file)
        expected = 0
        with get_session_factory(engine)() as session:
            for chunk in chunks:
                defs = extract_definitions(chunk.text_content, chunk.citation)
                # Literal definition terms test storage, not LLM generation.
                expansion = QueryExpansion(chunk.citation, legal_terms_of_art=[d.defined_term for d in defs])
                ingest_statute(session, chunk, defs, expansion)
                expected += len(defs)
            assert session.scalar(select(func.count()).select_from(Statute)) == len(chunks)
            assert session.scalar(select(func.count()).select_from(Definition)) == expected
            assert session.scalar(select(func.count()).select_from(SynonymKey)) == expected
            chunk = chunks[0]
            defs = extract_definitions(chunk.text_content, chunk.citation)
            assert defs
            before = expand_user_query(defs[0].defined_term, session)
            assert chunk.citation in before['ors_citations']
            ingest_statute(session, chunk, defs, QueryExpansion(chunk.citation, legal_terms_of_art=[d.defined_term for d in defs]))
            assert session.scalar(select(func.count()).select_from(Definition)) == expected
            stored = session.execute(select(Statute).where(Statute.citation == chunk.citation)).scalar_one()
            assert stored.text_content == chunk.text_content
            stored.text_content = 'rollback probe'
            session.flush()
            session.rollback()
            session.expire_all()
            assert session.execute(select(Statute).where(Statute.citation == chunk.citation)).scalar_one().text_content == chunk.text_content
        return dict(status='passed', postgres_version=version, statutes=len(chunks), definitions=expected,
                    schema_creation=True, unicode_roundtrip=True, query_expansion=True,
                    idempotent_reingestion=True, rollback=True, isolated_schema_removed=True,
                    llm_used=False)
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with control.begin() as conn:
                conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db-url-env', default='DATABASE_URL')
    p.add_argument('--ors-rows-file', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    try:
        result = verify(os.environ[args.db_url_env], args.ors_rows_file)
    except Exception as exc:
        # Driver errors may contain connection details. Do not emit credentials.
        orig = getattr(exc, 'orig', None)
        result = dict(status='failed', error_type=type(exc).__name__,
                      postgres_error_code=getattr(orig, 'pgcode', None))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
