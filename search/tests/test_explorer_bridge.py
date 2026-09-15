import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing

from search.build_synonym_db import expand_user_query, get_engine, get_session_factory
from search.explorer_bridge import AuditedClient, build_layer, export_bundle, validate_payload


class ExplorerBridgeTests(unittest.TestCase):
    def test_real_provider_json_shape_is_not_silently_coerced(self):
        valid=dict(layperson_questions=['One?','Two?','Three?'],colloquial_synonyms={'term':['plain phrase']},legal_terms_of_art=['term'])
        self.assertEqual(validate_payload(json.dumps(valid)),valid)
        for field,value in [('layperson_questions','not an array'),('legal_terms_of_art',[123]),('colloquial_synonyms',{'term':'not an array'})]:
            broken=dict(valid);broken[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):validate_payload(json.dumps(broken))

    def test_adapter_definition_search_and_unreviewed_publication_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'edition.db';output=root/'search.db'
            with closing(sqlite3.connect(source)) as db, db:
                db.execute('CREATE TABLE editions(edition_year INTEGER)')
                db.execute('INSERT INTO editions VALUES(2023)')
                db.execute('CREATE TABLE section_versions(ors_section TEXT,catchline TEXT,content_text TEXT,status TEXT,version_ordinal INTEGER)')
                db.execute('INSERT INTO section_versions VALUES(?,?,?,?,?)',('1.001','Definitions','As used in this section: (1) “Widget” means a device.','operative',0))
                db.execute('INSERT INTO section_versions VALUES(?,?,?,?,?)',('1.002','Repealed','Repealed.','repealed',0))
            report=asyncio.run(build_layer(source,output))
            self.assertEqual(report['counts']['statutes'],1)
            self.assertEqual(report['counts']['definitions'],1)
            engine=get_engine('sqlite:///'+str(output))
            try:
                with get_session_factory(engine)() as session:
                    self.assertEqual(expand_user_query('widget',session)['ors_citations'],['1.001'])
            finally:engine.dispose()
            with self.assertRaisesRegex(ValueError,'manually reviewed'):
                export_bundle(output,root/'site',root/'runtime')
            with self.assertRaisesRegex(ValueError,'new database'):
                asyncio.run(build_layer(source,output))
            reused=asyncio.run(build_layer(source,root/'reused.db',base_database=output))
            self.assertEqual(reused['counts'],report['counts'])
            with output.open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError,'unchanged definitions-only'):
                asyncio.run(build_layer(source,root/'rejected.db',base_database=output))

    def test_malformed_real_reply_is_retained_for_review(self):
        class InvalidClient:
            async def complete(self,prompt):return '{truncated'
        with tempfile.TemporaryDirectory() as directory:
            client=AuditedClient(InvalidClient(),directory)
            with self.assertRaises(ValueError):
                asyncio.run(client.complete('ORS Citation: 192.311\nStatutory text'))
            record=json.loads((Path(directory)/'192.311.json').read_text())
            self.assertFalse(record['json_valid'])
            self.assertEqual(record['raw_response'],'{truncated')
            self.assertFalse(client.records)


if __name__=='__main__':unittest.main()
