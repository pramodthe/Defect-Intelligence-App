import json
import uuid
import pytest
import psycopg
from psycopg import sql
from app.settings import settings
from app.workflows import checkpoint_session,build_research,execute_research
from app.recovery import backup,restore
from tests.conftest import publish_fixture
from tests.test_workflows_api import run_record


@pytest.mark.skipif(not settings.langgraph_checkpoint_dsn,reason='Local PostgreSQL required')
@pytest.mark.asyncio
async def test_checkpoint_dump_restore_and_canonical_reconciliation(store,ontology):
    name='checkpoint_test_'+uuid.uuid4().hex[:12]
    admin=settings.langgraph_checkpoint_dsn.replace('/checkpoints','/postgres')
    with psycopg.connect(admin,autocommit=True) as con:
        con.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    store.config.checkpoint_backend='postgres'
    store.config.langgraph_checkpoint_dsn=settings.langgraph_checkpoint_dsn.replace('/checkpoints','/'+name)
    try:
        publish_fixture(store,ontology)
        rid=run_record(store)
        async with checkpoint_session(store) as saver:
            await execute_research(store,build_research(store,saver,ontology),rid)
        saved=store.require('SELECT * FROM runs WHERE id=?',(rid,))
        original_claims=json.loads(saved['answer'])['claims']
        result=backup(store)
        assert result['manifest']['workflow_state']=='included'
        store.execute('UPDATE runs SET stale=1 WHERE id=?',(rid,))
        restored=restore(store,result['id'])
        assert restored['workflow_restored']
        final=store.require('SELECT * FROM runs WHERE id=?',(rid,))
        assert json.loads(final['answer'])['claims']==original_claims
        assert store.require("SELECT value FROM workspace WHERE key='maintenance'")['value']=='0'
        async with checkpoint_session(store) as saver:
            snapshot=await build_research(store,saver,ontology).aget_state({'configurable':{'thread_id':'research:'+rid}})
            assert snapshot.values['run_id']==rid
    finally:
        with psycopg.connect(admin,autocommit=True) as con:
            con.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
