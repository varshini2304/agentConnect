"""Idempotent seed data for the five initial company agents."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentInterest

SEED_AGENTS = (
    {
        "slug": "swiggy", "company_name": "Swiggy",
        "role": "Food delivery and merchant promotions", "industry": "food_delivery",
        "description": "Shares food delivery updates and merchant promotions.",
        "interests": (("category", "merchant_promotion", 1.0), ("category", "food_delivery", 1.0),
            ("keyword", "restaurant", 1.0), ("keyword", "food orders", 1.0),
            ("keyword", "merchant promotions", 1.0), ("keyword", "discounts", 0.8)),
    },
    {
        "slug": "phonepe", "company_name": "PhonePe",
        "role": "Digital payments, cashback and payment offers", "industry": "digital_payments",
        "description": "Shares digital payments, cashback and payment offer updates.",
        "interests": (("category", "merchant_promotion", 1.0), ("category", "digital_payments", 1.0),
            ("keyword", "cashback", 1.0), ("keyword", "payment offers", 1.0),
            ("keyword", "merchant promotions", 1.0)),
    },
    {
        "slug": "hdfc-bank", "company_name": "HDFC Bank",
        "role": "Banking, credit cards, EMI and merchant offers", "industry": "banking",
        "description": "Shares banking, card, EMI and merchant offer updates.",
        "interests": (("category", "merchant_promotion", 1.0), ("category", "banking", 1.0),
            ("keyword", "credit cards", 1.0), ("keyword", "EMI", 1.0),
            ("keyword", "banking offers", 1.0), ("keyword", "merchant promotions", 0.8)),
    },
    {
        "slug": "flipkart", "company_name": "Flipkart",
        "role": "E-commerce, shopping and retail promotions", "industry": "ecommerce",
        "description": "Shares e-commerce and retail promotion updates.",
        "interests": (("category", "retail_promotion", 1.0), ("category", "ecommerce", 1.0),
            ("keyword", "shopping", 1.0), ("keyword", "electronics", 1.0),
            ("keyword", "retail promotions", 1.0), ("keyword", "discounts", 0.8)),
    },
    {
        "slug": "shipping-corporation-of-india", "company_name": "Shipping Corporation of India",
        "role": "Shipping, maritime, cargo and logistics", "industry": "shipping_logistics",
        "description": "Shares shipping, maritime, cargo and logistics updates.",
        "interests": (("category", "shipping_logistics", 1.0), ("keyword", "maritime", 1.0),
            ("keyword", "cargo", 1.0), ("keyword", "ports", 1.0), ("keyword", "shipping", 1.0)),
    },
)


def seed_agents(db: Session) -> None:
    for definition in SEED_AGENTS:
        agent = db.scalar(select(Agent).where(Agent.slug == definition["slug"]))
        if agent is None:
            agent = Agent(
                slug=definition["slug"], company_name=definition["company_name"],
                role=definition["role"], industry=definition["industry"],
                description=definition["description"], is_active=True,
            )
            db.add(agent)
            db.flush()
        current = {
            (item.interest_type, item.value)
            for item in db.scalars(select(AgentInterest).where(AgentInterest.agent_id == agent.id))
        }
        for interest_type, value, weight in definition["interests"]:
            if (interest_type, value) not in current:
                db.add(AgentInterest(
                    agent_id=agent.id, interest_type=interest_type, value=value, weight=weight
                ))
    db.commit()
