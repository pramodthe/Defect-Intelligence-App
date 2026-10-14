import json
import time
import pytest
from app.settings import settings
from app.workflows import checkpoint_session,build_research,execute_research
from tests.conftest import publish_fixture
from tests.test_workflows_api import run_record


@pytest.mark.skipif(not settings.langgraph_checkpoint_dsn,reason='Local PostgreSQL checkpoint DSN required')
@pytest.mark.asyncio
async def test_real_postgres_checkpoint_interrupt_restart_resume(store,ontology):
    store.config.checkpoint_backend='postgres'
    store.config.langgraph_checkpoint_dsn=settings.langgraph_checkpoint_dsn
    publish_fixture(store,ontology)
    store.insert('projects',{'id':'pg-project','label':'Synthetic PostgreSQL integration','version':1})
    store.insert('contexts',{'id':'pg-context','project_id':'pg-project','purpose':'original_work_assessment','version':1,'facts':{},'created':time.time()})
    rid=run_record(store,'current','pg-context')
    async with checkpoint_session(store) as saver:
        graph=build_research(store,saver,ontology)
        await execute_research(store,graph,rid)
    assert store.require('SELECT status FROM runs WHERE id=?',(rid,))['status']=='clarification_required'
    before=store.require('SELECT tools FROM budgets WHERE owner_id=?',(rid,))['tools']
    async with checkpoint_session(store) as saver:
        graph=build_research(store,saver,ontology)
        await execute_research(store,graph,rid,{'expected_context_version':1,'facts':{'jurisdiction':'TEST'},'provenance':'Synthetic PostgreSQL fixture'})
        snapshot=await graph.aget_state({'configurable':{'thread_id':'research:'+rid}})
        assert snapshot.values['outcome']=='partial' and not snapshot.next
    run=store.require('SELECT * FROM runs WHERE id=?',(rid,))
    assert run['status']=='partial' and run['checkpoint_id']
    assert store.require('SELECT tools FROM budgets WHERE owner_id=?',(rid,))['tools']>before
    assert json.loads(run['answer'])['claims']
