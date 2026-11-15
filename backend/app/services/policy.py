"""Central business policy routing. Authentication and resource ACLs precede this layer."""
from dataclasses import dataclass
import re

from app.services.response_generation import PolicyViolationError, validate_policy

CATEGORIES = ("general_information", "product_announcement", "promotional_offer", "financial_claim", "partnership_proposal", "binding_commitment", "external_action")
PLATFORM_APPROVAL = {"promotional_offer", "financial_claim", "binding_commitment", "external_action"}


@dataclass(frozen=True)
class PolicyEvaluation:
    disposition: str
    category: str
    reasons: tuple[str, ...]


def classify_categories(content: str) -> tuple[str, ...]:
    text = content.casefold()
    # shortcut: deterministic classification flags explicit claims; semantic review still requires a human.
    patterns = (
        ("external_action", r"\b(?:transfer funds|send (?:money|payment)|execute (?:a )?(?:payment|trade)|purchase on behalf|delete (?:the )?account|external action)\b"),
        ("binding_commitment", r"\b(?:binding|we (?:agree|commit|promise|shall)|contract(?:ual)? commitment|legally obligated)\b"),
        ("financial_claim", r"\b(?:guarantee[ds]?|guaranteed|risk.free|interest rate|annual return|investment return|apr|apy)\b|\d+(?:\.\d+)?\s*%\s*(?:return|interest|yield)"),
        ("promotional_offer", r"\b(?:we|our company)\s+(?:(?:will|can|may|shall)\s+)*(?:offer|refund|credit|discount)\b|\d+(?:\.\d+)?\s*%\s*(?:cashback|off|discount)|\b(?:exclusive offer|promotional offer|free delivery|coupon code)\b|\b(?:cashback|discount)\s*(?:of\s*)?\d"),
        ("partnership_proposal", r"\b(?:partnership|partner with|commercial proposal)\b"),
        ("product_announcement", r"\b(?:launch(?:ing|ed)?|product announcement|new product|clinically proven|verified product claim)\b"),
    )
    detected = tuple(category for category, pattern in patterns if re.search(pattern, text))
    if re.search(r"(?:[$₹€£]\s*\d|\b(?:usd|inr|eur|gbp|rs\.?)\s*\d|\d+(?:\.\d+)?\s*%)", text) and not {"financial_claim", "promotional_offer"}.intersection(detected):
        detected = (*detected, "financial_claim")
    return detected or ("general_information",)


def classify_content(content: str) -> str:
    return classify_categories(content)[0]


def evaluate_action(*, action: str, content: str, company_policy: dict, configs: list[dict], source_content: str = "", business_category: str = "", requested_approval: bool = False) -> PolicyEvaluation:
    categories = classify_categories(content)
    business_category = business_category.strip().casefold()
    if business_category in CATEGORIES and business_category not in categories:
        categories = (*categories, business_category)
    category = next((value for value in categories if value != "general_information"), "general_information")
    policies = [company_policy, *configs]
    rejects, approvals = [], []
    permission = {"message.reply": "allow_replies", "publication.publish": "allow_public", "conversation.initiate": "allow_initiation", "participant.invite": "allow_invitations", "knowledge.retrieve": "allow_knowledge"}.get(action)
    if company_policy.get("emergency_paused", False):
        rejects.append("company.emergency_paused")
    if permission and any(not p.get(permission, True) for p in policies):
        rejects.append("permission." + permission)
    if action == "message.reply" and any("reply" not in p.get("allowed_actions", ["reply"]) for p in policies):
        rejects.append("permission.reply")
    text = (source_content + " " + content).casefold()
    if any(term.casefold() in text for p in policies for term in p.get("excluded_topics", []) if term.strip()):
        rejects.append("content.excluded_topic")
    restricted = {str(c).casefold() for c in company_policy.get("restricted_categories", [])}
    if restricted.intersection(categories) or business_category.casefold() in restricted:
        rejects.append("content.restricted_category")
    for value in categories:
        if value in PLATFORM_APPROVAL:
            approvals.append("platform.category." + value)
    if "product_announcement" in categories and re.search(r"clinically proven|verified product claim|best in the world", content, re.I):
        approvals.append("platform.product_claim_verification")
    for value in categories:
        if any(value in p.get("approval_categories", []) for p in policies):
            approvals.append("policy.approval_category." + value)
    if any(p.get("require_approval", False) for p in configs) or (action.startswith("publication.") and company_policy.get("require_publish_approval", False)):
        approvals.append("policy.require_approval")
    if any(term.casefold() in text for p in policies for term in p.get("approval_topics", []) if term.strip()):
        approvals.append("policy.approval_topic")
    if requested_approval:
        approvals.append("agent.requested_approval")
    reasons = tuple(dict.fromkeys(rejects or approvals))
    return PolicyEvaluation("reject" if rejects else "approval" if approvals else "allow", category, reasons)
