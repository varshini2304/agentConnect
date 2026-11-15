"""Pure deterministic relevance scoring. This module has no database or provider dependencies."""
from dataclasses import asdict, dataclass, field
import re
import unicodedata
from typing import Iterable


@dataclass(frozen=True)
class Interest:
    interest_type: str
    value: str
    weight: float = 1.0


@dataclass(frozen=True)
class AgentProfile:
    id: int
    name: str
    active: bool
    interests: tuple[Interest, ...] = ()


@dataclass(frozen=True)
class PostProfile:
    id: int
    author_agent_id: int
    title: str
    content: str
    category: str


@dataclass(frozen=True)
class Relationship:
    source_agent_id: int
    target_agent_id: int
    relation: str
    weight: float = 1.0


@dataclass(frozen=True)
class RelevanceConfig:
    threshold: float = 0.25
    top_k: int = 5

    def __post_init__(self):
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if self.top_k < 0:
            raise ValueError("top_k cannot be negative")


@dataclass
class ScoringResult:
    agent_id: int
    agent_name: str
    eligible: bool
    category_score: float
    keyword_score: float
    relationship_score: float
    final_score: float
    matched_categories: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    selected: bool = False
    explanation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# A small, explicit synonym set. Matching remains phrase-boundary based.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "cashback": ("cash back",),
    "credit cards": ("credit card",),
    "banking offers": ("bank offer", "bank offers", "banking offer"),
    "merchant promotions": ("merchant promotion",),
    "food orders": ("food order",),
    "retail promotions": ("retail promotion",),
    "ecommerce": ("e-commerce", "online shopping"),
    "shipping logistics": ("shipping", "logistics"),
    "integrations": ("integration", "software integration", "systems integration", "system integration", "api integration"),
    "system integrations": ("system integration", "systems integration", "software integration", "api integration"),
    "systems integration": ("system integration", "software integration", "api integration"),
    "software integrations": ("software integration", "systems integration", "system integration", "api integration"),
    "customer portals": ("customer portal", "portal"),
    "partner portals": ("partner portal", "portal"),
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(value.split())


def _phrase_matches(text: str, phrase: str) -> bool:
    normalized = normalize(phrase)
    if not normalized:
        return False
    return re.search(r"(?<!\w)" + re.escape(normalized) + r"(?!\w)", text) is not None


def _keyword_match(text: str, keyword: str) -> bool:
    normalized = normalize(keyword)
    candidates = (normalized, *SYNONYMS.get(normalized, ()))
    # Also accept synonyms in the opposite direction, for example credit card(s).
    candidates += tuple(alias for canonical, aliases in SYNONYMS.items() if normalized in aliases for alias in (canonical,))
    return any(_phrase_matches(text, candidate) for candidate in candidates)


def _exclusion_match(text: str, terms: Iterable[str]) -> str | None:
    return next((term for term in terms if _phrase_matches(text, term)), None)


def evaluate_relevance(
    post: PostProfile,
    agents: Iterable[AgentProfile],
    relationships: Iterable[Relationship] = (),
    config: RelevanceConfig = RelevanceConfig(),
) -> list[ScoringResult]:
    """Score profiles, apply hard eligibility rules, then deterministic threshold/top-K."""
    relationship_rows = tuple(relationships)
    post_text = normalize(f"{post.title} {post.category} {post.content}")
    results: list[ScoringResult] = []
    raw_scores: dict[int, float] = {}

    for agent in agents:
        categories = [i.value for i in agent.interests if i.interest_type == "category"]
        keywords = [i.value for i in agent.interests if i.interest_type == "keyword"]
        exclusions = [i.value for i in agent.interests if i.interest_type == "exclude"]
        matched_categories = sorted({value for value in categories
                                     if normalize(value) == normalize(post.category)
                                     or _keyword_match(normalize(post.category), value)})
        matched_keywords = sorted({value for value in keywords if _keyword_match(post_text, value)}, key=str.casefold)
        category_score = 1.0 if matched_categories else 0.0
        keyword_score = len(matched_keywords) / len(keywords) if keywords else 0.0

        blocked = any(
            row.relation == "block"
            and {row.source_agent_id, row.target_agent_id} == {post.author_agent_id, agent.id}
            for row in relationship_rows
        )
        partner_weights = [
            min(1.0, max(0.0, row.weight))
            for row in relationship_rows
            if row.relation == "partner"
            and {row.source_agent_id, row.target_agent_id} == {post.author_agent_id, agent.id}
        ]
        relationship_score = max(partner_weights, default=0.0)
        excluded_term = _exclusion_match(post_text, exclusions)
        has_interests = bool(categories or keywords or exclusions)
        topical_match = bool(category_score or matched_keywords)

        reasons: list[str] = []
        eligible = True
        if agent.id == post.author_agent_id:
            eligible = False
            reasons.append("post author is excluded")
        if not agent.active:
            eligible = False
            reasons.append("agent is inactive")
        if blocked:
            eligible = False
            reasons.append("blocked relationship is a hard exclusion")
        if excluded_term:
            eligible = False
            reasons.append(f"matched exclusion term: {excluded_term}")
        if not has_interests:
            eligible = False
            reasons.append("agent has no configured interests")
        if not topical_match:
            eligible = False
            reasons.append("no topical category or keyword match")
        raw_score = 0.55 * category_score + 0.35 * keyword_score + 0.10 * relationship_score
        final_score = round(raw_score, 6)
        if topical_match:
            reasons.append("topical relevance found")
        if relationship_score:
            reasons.append(f"partner boost {relationship_score:.3f}")
        result = ScoringResult(
            agent_id=agent.id,
            agent_name=agent.name,
            eligible=eligible,
            category_score=category_score,
            keyword_score=round(keyword_score, 6),
            relationship_score=relationship_score,
            final_score=final_score,
            matched_categories=matched_categories,
            matched_keywords=matched_keywords,
            explanation="; ".join(reasons) if reasons else "not eligible",
        )
        # Keep the unrounded value for selection; final_score is presentation/storage only.
        raw_scores[agent.id] = raw_score
        results.append(result)

    candidates = sorted(
        (result for result in results if result.eligible and raw_scores[result.agent_id] >= config.threshold),
        key=lambda result: (-raw_scores[result.agent_id], result.agent_id),
    )[:config.top_k]
    selected_ids = {result.agent_id for result in candidates}
    for result in results:
        if result.agent_id in selected_ids:
            result.selected = True
            result.explanation += f"; selected at threshold {config.threshold:.3f}"
        elif result.eligible:
            result.explanation += (
                f"; below threshold {config.threshold:.3f}"
                if raw_scores[result.agent_id] < config.threshold
                else "; outside top_k"
            )
    return sorted(results, key=lambda result: result.agent_id)


