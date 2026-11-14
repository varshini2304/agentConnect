import pytest
from pydantic import ValidationError

from app.adapters import simulated_sources
from app.adapters.simulated_sources import (
    InvalidSourcePayloadError, UnknownScenarioError, get_scenario, list_scenarios,
)
from app.schemas.post import SourcePayload


def test_three_simulated_scenarios_are_structured():
    payloads = [get_scenario(scenario) for scenario in list_scenarios()]
    assert len(payloads) == 3
    assert {item.author_agent_slug for item in payloads} == {
        "swiggy", "flipkart", "shipping-corporation-of-india"
    }
    assert all(item.source_type == "simulated" for item in payloads)


def test_unknown_scenario_is_rejected():
    with pytest.raises(UnknownScenarioError):
        get_scenario("missing")


def test_invalid_source_payload_is_rejected(monkeypatch):
    monkeypatch.setitem(simulated_sources._SCENARIOS, "broken", {
        "scenario_id": "broken", "author_agent_slug": "swiggy", "title": "Title",
        "content": "Content", "category": "food", "source_type": "simulated", "source_ref": "",
    })
    with pytest.raises(InvalidSourcePayloadError):
        get_scenario("broken")
    with pytest.raises(ValidationError):
        SourcePayload.model_validate({
            "scenario_id": "broken", "author_agent_slug": "swiggy", "title": "Title",
            "content": "Content", "category": "food", "source_type": "simulated", "source_ref": "",
        })


def test_demo_publishes_scenario_and_deduplicates(client):
    payload = {"scenario_id": "swiggy-diwali-promotion"}
    first = client.post("/api/demo/run", json=payload)
    again = client.post("/api/demo/run", json=payload)
    assert first.status_code == 201
    assert first.json()["created"] is True
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert again.json()["post"]["id"] == first.json()["post"]["id"]


def test_demo_unknown_scenario_returns_404(client):
    assert client.post("/api/demo/run", json={"scenario_id": "none"}).status_code == 404


def test_health_checks_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
