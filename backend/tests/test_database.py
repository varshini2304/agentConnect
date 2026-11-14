import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def test_startup_initializes_database_and_seeds_five_agents(client):
    response = client.get("/api/agents")
    assert response.status_code == 200
    assert len(response.json()) == 5


def test_sqlite_foreign_keys_are_enforced(app, client):
    with app.state.db_engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO posts "
                "(author_agent_id, title, content, category, content_hash, source_type) "
                "VALUES (99999, 't', 'c', 'category', lower(hex(randomblob(32))), 'manual')"
            ))
