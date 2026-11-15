"""Optional production-engine acceptance, always in a deliberately empty test database."""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from auth_helpers import CookieClient
from app.adapters.fake_response import FakeResponseAdapter
from app.db.session import make_engine
from app.main import create_app
from app.services.runtime import claim_work
from test_governance import test_phase3_complete_three_company_governed_workflow as complete_workflow, policy
from test_conversations_runtime import agent, register, conversation, accept, send, REPLY


def test_postgres_real_governance_conversations_and_atomic_claims(monkeypatch):
    url = os.getenv('AGENTCONNECT_TEST_POSTGRES_RUNTIME_URL')
    if not url:
        pytest.skip('Set an empty disposable PostgreSQL database URL for runtime acceptance')
    assert url.startswith('postgresql'), 'This acceptance test requires PostgreSQL'
    monkeypatch.setenv('AGENTCONNECT_ENABLE_FAKE', 'true')
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")) == 0, 'Refusing a nonempty test database'
        adapter = FakeResponseAdapter({i: REPLY for i in range(1, 30)})
        app = create_app(db_engine=engine, runtime_adapter=adapter)
        with CookieClient(app) as client:
            complete_workflow((client, app, adapter))
            ha, hb = register(client, 'ConcurrentA'), register(client, 'ConcurrentB')
            a, b = agent(client, ha, 'ConcurrentA'), agent(client, hb, 'ConcurrentB')
            policy(client, hb, daily_execution_budget=1)
            conv = conversation(client, ha, a, b, key='pg-concurrent')
            accept(client, hb, conv['id'])
            send(client, ha, conv['id'], a['id'], key='pg-one')
            send(client, ha, conv['id'], a['id'], key='pg-two')
            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda _: claim_work(app.state.session_factory), range(2)))
            assert sum(work is not None for work in claims) == 1
    finally:
        engine.dispose()
