"""Idempotent seed data for the five initial company agents."""
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentInterest, Post
from app.db.network import AgentAccount, AgentVersion, Company, CompanyMember, CompanyRole, CompanySettings, User
from app.schemas.network import AgentConfig, CompanyPolicy
from app.services.security import hash_password, seed_roles
from app.core.config import get_gemini_model

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


def seed_demo_network(db: Session) -> User | None:
    """Provision the five bundled demo publishers only into a genuinely fresh database."""
    if (db.scalar(select(func.count(Company.id))) or db.scalar(select(func.count(AgentAccount.id)))
            or db.scalar(select(func.count(Agent.id)).where(Agent.company_id.is_not(None)))
            or db.scalar(select(func.count(Post.id)))):
        return None

    user = db.scalar(select(User).where(User.email == "agentconnect-demo-service@invalid.local"))
    if user is None:
        user = User(email="agentconnect-demo-service@invalid.local", name="AgentConnect Demo Service",
                    password_hash=hash_password(secrets.token_urlsafe(48)), status="active")
        db.add(user)
        db.flush()

    categories = {
        "swiggy": "merchant_promotion", "hdfc-bank": "banking", "flipkart": "retail_promotion",
        "phonepe": "merchant_promotion", "shipping-corporation-of-india": "shipping_logistics",
    }
    definitions = {row["slug"]: row for row in SEED_AGENTS}
    for slug in ("swiggy", "hdfc-bank", "flipkart", "phonepe", "shipping-corporation-of-india"):
        definition = definitions[slug]
        policy = CompanyPolicy(require_invitation_approval=False).model_dump()
        company = Company(name=definition["company_name"], slug=slug, status="active",
                          network_opt_in=True, policy=policy, policy_version=1)
        db.add(company)
        db.flush()
        seed_roles(db, company)
        owner_role = db.scalar(select(CompanyRole).where(CompanyRole.company_id == company.id, CompanyRole.slug == "owner"))
        db.add_all([CompanySettings(company_id=company.id, industry=definition["industry"], onboarding_complete=True),
                    CompanyMember(company_id=company.id, user_id=user.id, role="owner", role_id=owner_role.id)])

        agent = db.scalar(select(Agent).where(Agent.slug == slug))
        if agent is None or agent.company_id is not None:
            db.rollback()
            return None
        agent.company_id = company.id
        category = categories[slug]
        config = AgentConfig(
            name=definition["company_name"], description=definition["description"], role=definition["role"],
            domain=definition["industry"], purpose=definition["description"],
            categories=[item[1] for item in definition["interests"] if item[0] == "category"],
            keywords=[item[1] for item in definition["interests"] if item[0] == "keyword"],
            discoverable=True, allow_public=True, allow_direct=True, allow_group=True,
            provider="gemini", model=get_gemini_model(), allowed_publishing_categories=[category],
            discussion_topics=[item[1] for item in definition["interests"] if item[0] in ("category", "keyword")],
        ).model_dump()
        version = AgentVersion(agent_id=agent.id, version=1, config=config, created_by=user.id)
        db.add(version)
        db.flush()
        db.add(AgentAccount(id=agent.id, company_id=company.id, slug=slug, state="active",
                            active_version_id=version.id, config_version_id=version.id))
    db.commit()
    return user
