import asyncio
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import sys

import pytest

from parser.agent_data import AgentData, connect, prepare
from parser.database import SCHEMA


@pytest.fixture
def serving(tmp_path):
    source=tmp_path/'source.db'
    with closing(sqlite3.connect(source)) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO editions VALUES(2023,NULL,'https://example.org/edition','sample')")
        db.execute("INSERT INTO chapters VALUES('90','Housing',1,2023)")
        db.execute("INSERT INTO sources VALUES('https://example.org/ch90','abc',123)")
        db.execute("INSERT INTO chapter_sources VALUES(2023,'90','https://example.org/ch90')")
        for citation,text in [('90.100','A tenant occupies a dwelling.'),('90.110','Another tenant with a dwelling.')]:
            db.execute('INSERT INTO sections VALUES(?,?,?,?,?)',(citation,'90','Definitions',text,2023))
            db.execute('INSERT INTO section_versions VALUES(?,?,?,?,?,?,?,?)',(2023,citation,0,'Definitions',text,'operative',None,None))
        db.execute("INSERT INTO section_versions VALUES(2023,'90.100',1,'Alternate','Future wording about a unicorn.','operative',NULL,'Effective later')")
        db.execute("INSERT INTO amendments VALUES('a','HB 1',2024,'90.100','AMEND','new text')")
        db.execute("INSERT INTO pending_changes VALUES('p','90.100','HB 1',NULL,'Applies upon an event')")
        db.execute("INSERT INTO pending_change_sources VALUES('p',2023,'90','https://example.org/ch90')")
        db.commit()
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    output=tmp_path/'serving.db'
    prepare(source,output)
    assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
    return output


def test_search_versions_filters_pagination_and_literal_input(serving):
    service=AgentData(serving)
    page=service.search_sections('tenant',limit=1)
    assert page['next_offset']==1
    assert service.search_sections('tenant',limit=1,offset=1)['items'][0]['id']!=page['items'][0]['id']
    assert service.search_sections('unicorn')['items'][0]['version_ordinal']==1
    assert not service.search_sections('tenant',edition=2021)['items']
    assert not service.search_sections('tenant',chapter='91')['items']
    assert len(service.search_sections('ORS 90.100')['items'])==2
    assert not service.search_sections('tenant OR injected')['items']
    for query in ('', '%%%','x'*301):
        with pytest.raises(ValueError):service.search_sections(query)
    with pytest.raises(ValueError):service.search_sections('tenant',limit=101)
    with closing(connect(serving)) as db:
        with pytest.raises(sqlite3.OperationalError):db.execute('DELETE FROM sections')


def test_lookup_provenance_and_unknown_dates(serving):
    service=AgentData(serving)
    result=service.get_section('ORS 90.100',2023)
    assert len(result['versions'])==2
    assert result['sources'][0]['sha256']=='abc'
    assert service.get_pending_changes('90.100')['items'][0]['effective_date'] is None
    assert service.get_amendments('90.100',2024)['items'][0]['id']=='a'
    assert not service.get_amendments('90.100',2025)['items']
    with pytest.raises(LookupError):service.get_section('90.100',2021)


def test_http_contract(serving):
    pytest.importorskip('fastapi')
    from fastapi.testclient import TestClient
    from parser.agent_service import create_app
    with TestClient(create_app(serving)) as client:
        assert client.get('/v1/dataset').json()['counts']['sections']==2
        assert client.get('/v1/search',params={'query':'tenant'}).json()['items']
        assert client.get('/v1/section',params={'citation':'90.100','edition':2023}).status_code==200
        assert client.get('/v1/section',params={'citation':'90.100','edition':2021}).status_code==404
        assert client.get('/v1/search',params={'query':'%%%'}).status_code==400
        assert client.get('/v1/search',params={'query':'tenant','limit':'bad'}).status_code==422
        assert client.post('/v1/search').status_code==405
        assert len(client.get('/openapi.json').json()['paths'])==5


def test_actual_mcp_stdio(serving):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        parameters=StdioServerParameters(command=sys.executable,args=['-m','parser.agent_service','mcp','--database',str(serving)])
        async with stdio_client(parameters) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                listed=await client.list_tools()
                assert len(listed.tools)==5
                result=await client.call_tool('search_sections',{'query':'tenant'})
                assert not result.isError
                assert result.structuredContent['items'][0]['ors_section']=='90.100'
                bad=await client.call_tool('get_section',{'citation':'invalid','edition':2023})
                assert bad.isError
    asyncio.run(run())
