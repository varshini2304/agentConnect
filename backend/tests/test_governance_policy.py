"""Backend classification is conservative routing, never an LLM permission grant."""
from app.services.policy import evaluate_action


def evaluate(text, **kwargs):
    return evaluate_action(action="message.reply", content=text, company_policy=kwargs.pop("company_policy", {}), configs=kwargs.pop("configs", [{}]), **kwargs)


def test_restricted_content_requires_review_before_execution():
    for text, category in [("Get 20% cashback today", "promotional_offer"), ("We guarantee a 12% return", "financial_claim"), ("We agree to pay the binding contract fee", "binding_commitment"), ("Please transfer funds to our account", "external_action")]:
        result = evaluate(text)
        assert result.disposition == "approval", (text, result)
        assert result.category == category
        assert result.reasons
    assert evaluate("Discuss public payments and cashback eligibility.").disposition == "allow"


def test_hard_policy_always_precedes_approval():
    assert evaluate("Get 20% cashback", company_policy={"allow_replies": False}).disposition == "reject"
    assert evaluate("Ordinary reply", configs=[{"allow_replies": False}, {"allow_replies": True}]).disposition == "reject"
    assert evaluate("Ordinary reply", company_policy={"emergency_paused": True}).disposition == "reject"
    assert evaluate("Private acquisition plans", company_policy={"excluded_topics": ["acquisition"]}).disposition == "reject"
    assert evaluate("Get 20% cashback", company_policy={"restricted_categories": ["promotional_offer"]}).disposition == "reject"


def test_company_and_pinned_agent_approval_requirements_are_combined():
    assert evaluate("Potential partnership discussion", company_policy={"approval_categories": ["partnership_proposal"]}).disposition == "approval"
    assert evaluate("Please review payments", configs=[{"require_approval": True}, {}]).disposition == "approval"
    assert evaluate("Please review payments", configs=[{}, {}], source_content="restricted quote", company_policy={"approval_topics": ["quote"]}).disposition == "approval"
