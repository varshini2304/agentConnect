"""Structured simulated information sources. This adapter has no database access."""
from pydantic import ValidationError

from app.schemas.post import SourcePayload


class UnknownScenarioError(KeyError):
    pass


class InvalidSourcePayloadError(ValueError):
    pass


_SCENARIOS = {
    "swiggy-diwali-promotion": {
        "scenario_id": "swiggy-diwali-promotion",
        "author_agent_slug": "swiggy",
        "title": "Diwali food-order promotion",
        "content": "Diwali food promotion: 15% off on food orders. Customers can use PhonePe payment cashback and an HDFC credit card bank offer.",
        "category": "merchant_promotion",
        "source_type": "simulated",
        "source_ref": "scenario:swiggy-diwali-promotion",
    },
    "flipkart-electronics-promotion": {
        "scenario_id": "flipkart-electronics-promotion",
        "author_agent_slug": "flipkart",
        "title": "Electronics shopping promotion",
        "content": "Flipkart announces an electronics shopping promotion with discounts for customers.",
        "category": "retail_promotion",
        "source_type": "simulated",
        "source_ref": "scenario:flipkart-electronics-promotion",
    },
    "sci-maritime-cargo-update": {
        "scenario_id": "sci-maritime-cargo-update",
        "author_agent_slug": "shipping-corporation-of-india",
        "title": "Maritime cargo update",
        "content": "Shipping Corporation reports an update about maritime cargo and port operations.",
        "category": "shipping_logistics",
        "source_type": "simulated",
        "source_ref": "scenario:sci-maritime-cargo-update",
    },
}


def list_scenarios() -> list[str]:
    return list(_SCENARIOS)


def get_scenario(scenario_id: str) -> SourcePayload:
    try:
        raw_payload = _SCENARIOS[scenario_id]
    except KeyError as exc:
        raise UnknownScenarioError(scenario_id) from exc
    try:
        return SourcePayload.model_validate(raw_payload)
    except ValidationError as exc:
        raise InvalidSourcePayloadError(f"Invalid payload for scenario {scenario_id}") from exc

