"""Hybrid relevance scoring combining category matching, keyword matching, and semantic embeddings.

This module provides pure mathematical and linguistic matching without database dependencies.
Embeddings can be passed into PostProfile and AgentProfile or evaluated purely deterministically.
"""
from dataclasses import asdict, dataclass, field
import math
import re
from typing import Iterable, Sequence
import unicodedata

from app.core.config import (
    get_relevance_deterministic_weight,
    get_relevance_semantic_match_threshold,
    get_relevance_semantic_weight,
    get_relevance_threshold,
    get_relevance_top_k,
)


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
    embedding: tuple[float, ...] | Sequence[float] | None = None
    role: str = ""
    domain: str = ""
    description: str = ""


@dataclass(frozen=True)
class PostProfile:
    id: int
    author_agent_id: int
    title: str
    content: str
    category: str
    embedding: tuple[float, ...] | Sequence[float] | None = None


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
    deterministic_weight: float = 0.60
    semantic_weight: float = 0.40
    semantic_match_threshold: float = 0.20

    def __post_init__(self):
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if self.top_k < 0:
            raise ValueError("top_k cannot be negative")
        if self.deterministic_weight < 0.0 or self.semantic_weight < 0.0:
            raise ValueError("weights must be non-negative")
        if self.deterministic_weight == 0.0 and self.semantic_weight == 0.0:
            raise ValueError("at least one weight must be positive")


def get_default_relevance_config() -> RelevanceConfig:
    """Load default relevance configuration from backend settings."""
    return RelevanceConfig(
        threshold=get_relevance_threshold(),
        top_k=get_relevance_top_k(),
        deterministic_weight=get_relevance_deterministic_weight(),
        semantic_weight=get_relevance_semantic_weight(),
        semantic_match_threshold=get_relevance_semantic_match_threshold(),
    )


@dataclass
class ScoringResult:
    agent_id: int
    agent_name: str
    eligible: bool
    category_score: float
    keyword_score: float
    relationship_score: float
    final_score: float
    deterministic_score: float = 0.0
    semantic_score: float = 0.0
    matched_categories: list[str] = field(default_factory=list)
    matched_keywords: list[str] = field(default_factory=list)
    selected: bool = False
    explanation: str = ""

    @property
    def semantic_similarity(self) -> float:
        return self.semantic_score

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
    value = unicodedata.normalize("NFKC", value or "").casefold()
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


def _compute_cosine_similarity(vec1: Sequence[float] | None, vec2: Sequence[float] | None) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = 0.0
    norm1_sq = 0.0
    norm2_sq = 0.0
    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1_sq += a * a
        norm2_sq += b * b
    if norm1_sq <= 0.0 or norm2_sq <= 0.0:
        return 0.0
    sim = dot / (math.sqrt(norm1_sq) * math.sqrt(norm2_sq))
    return max(0.0, min(1.0, sim))


def evaluate_relevance(
    post: PostProfile,
    agents: Iterable[AgentProfile],
    relationships: Iterable[Relationship] = (),
    config: RelevanceConfig = RelevanceConfig(),
) -> list[ScoringResult]:
    """Score profiles, apply hard eligibility rules, then hybrid threshold/top-K selection."""
    relationship_rows = tuple(relationships)
    post_text = normalize(f"{post.title} {post.category} {post.content}")
    results: list[ScoringResult] = []
    raw_scores: dict[int, float] = {}

    # Normalize weights so they sum to 1.0
    total_weight = config.deterministic_weight + config.semantic_weight
    if total_weight > 0.0:
        w_det = config.deterministic_weight / total_weight
        w_sem = config.semantic_weight / total_weight
    else:
        w_det, w_sem = 1.0, 0.0

    has_post_embedding = bool(post.embedding and any(post.embedding))

    for agent in agents:
        categories = [i.value for i in agent.interests if i.interest_type == "category"]
        keywords = [i.value for i in agent.interests if i.interest_type == "keyword"]
        exclusions = [i.value for i in agent.interests if i.interest_type == "exclude"]

        matched_categories = sorted({
            value for value in categories
            if normalize(value) == normalize(post.category) or _keyword_match(normalize(post.category), value)
        })
        matched_keywords = sorted(
            {value for value in keywords if _keyword_match(post_text, value)},
            key=str.casefold,
        )

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

        # Semantic similarity calculation
        has_agent_embedding = bool(agent.embedding and any(agent.embedding))
        can_use_semantic = has_post_embedding and has_agent_embedding

        if can_use_semantic:
            raw_sim = _compute_cosine_similarity(post.embedding, agent.embedding)
            semantic_score = round(raw_sim, 6)
        else:
            semantic_score = 0.0

        # Topical match: category, keyword, or semantic similarity exceeding the threshold
        topical_match = bool(
            category_score > 0
            or matched_keywords
            or (can_use_semantic and semantic_score >= config.semantic_match_threshold)
        )

        # Hard exclusions: strict eligibility fences that no embedding or partner score may override
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
            reasons.append("no topical category, keyword, or semantic match")

        # Deterministic component score (0.0 to 1.0)
        deterministic_raw = 0.55 * category_score + 0.35 * keyword_score + 0.10 * relationship_score
        deterministic_score = round(deterministic_raw, 6)

        # Combine into hybrid score
        if can_use_semantic:
            raw_score = w_det * deterministic_raw + w_sem * semantic_score
        else:
            # Fallback to pure deterministic score when semantic embeddings are absent or disabled
            raw_score = deterministic_raw

        final_score = round(raw_score, 6)

        if topical_match:
            reasons.append("topical relevance found")
        if matched_categories:
            reasons.append(f"category match: {', '.join(matched_categories)}")
        if matched_keywords:
            reasons.append(f"keyword match: {', '.join(matched_keywords)}")
        if can_use_semantic and semantic_score > 0.0:
            reasons.append(f"semantic similarity {semantic_score:.3f}")
        if relationship_score > 0.0:
            reasons.append(f"partner boost {relationship_score:.3f}")

        result = ScoringResult(
            agent_id=agent.id,
            agent_name=agent.name,
            eligible=eligible,
            category_score=category_score,
            keyword_score=round(keyword_score, 6),
            relationship_score=relationship_score,
            deterministic_score=deterministic_score,
            semantic_score=semantic_score,
            final_score=final_score,
            matched_categories=matched_categories,
            matched_keywords=matched_keywords,
            explanation="; ".join(reasons) if reasons else "not eligible",
        )
        raw_scores[agent.id] = raw_score
        results.append(result)

    # Recipient selection: filter eligible >= threshold, rank descending by score with deterministic agent_id tie-break
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
