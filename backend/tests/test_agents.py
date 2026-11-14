def agent_payload(slug="test-agent"):
    return {
        "slug": slug,
        "company_name": "Test Co",
        "role": "Testing",
        "industry": "software",
        "description": "A test agent.",
        "interests": [{"interest_type": "keyword", "value": "testing", "weight": 0.5}],
    }


def test_seed_is_idempotent(client, app):
    from sqlalchemy import func, select

    from app.db.models import Agent, AgentInterest
    from app.db.seed import seed_agents

    with app.state.session_factory() as db:
        seed_agents(db)
        first_counts = (
            db.scalar(select(func.count()).select_from(Agent)),
            db.scalar(select(func.count()).select_from(AgentInterest)),
        )
        seed_agents(db)
        second_counts = (
            db.scalar(select(func.count()).select_from(Agent)),
            db.scalar(select(func.count()).select_from(AgentInterest)),
        )

    assert first_counts == second_counts
    assert first_counts[0] == 5


def test_agent_listing_and_retrieval(client):
    response = client.get("/api/agents")
    assert response.status_code == 200
    assert {item["slug"] for item in response.json()} == {
        "swiggy", "phonepe", "hdfc-bank", "flipkart", "shipping-corporation-of-india"
    }
    agent_id = response.json()[0]["id"]
    detail = client.get(f"/api/agents/{agent_id}")
    assert detail.status_code == 200
    assert detail.json()["interests"]


def test_agent_registration_and_duplicate_slug(client):
    response = client.post("/api/agents", json=agent_payload())
    assert response.status_code == 201
    assert response.json()["slug"] == "test-agent"
    duplicate = client.post("/api/agents", json=agent_payload(" TEST-agent "))
    assert duplicate.status_code == 409


def test_invalid_agent_input(client):
    assert client.post("/api/agents", json=agent_payload("bad slug")).status_code == 422


def test_patch_agent_active_status(client):
    agent_id = client.get("/api/agents").json()[0]["id"]
    response = client.patch(f"/api/agents/{agent_id}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_unknown_agent_returns_404(client):
    assert client.get("/api/agents/999999").status_code == 404
    assert client.patch("/api/agents/999999", json={"is_active": False}).status_code == 404

