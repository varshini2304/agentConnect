"""Unit and integration tests for the hybrid relevance engine.

Tests verify deterministic matching preservation, semantic embeddings via DeterministicFakeEmbeddingProvider,
cosine similarity, hybrid score combination, hard exclusions, graceful fallback on model failure,
caching, persistence, ranking, and top-K selection.
"""
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_relevance_threshold
from app.db.models import Agent, AgentInterest, AgentRelationship, Base, Post, RoutingDecision
from app.db.network import AgentAccount, AgentVersion, Company, CompanyMember, DiscoveryRecord, Publication, StoredEmbedding
from app.services.embedding_service import (
    BaseEmbeddingProvider,
    DeterministicFakeEmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingService,
    clear_embedding_cache,
    cosine_similarity,
    default_embedding_service,
)
from app.services.relevance import (
    AgentProfile,
    Interest,
    PostProfile,
    Relationship,
    RelevanceConfig,
    evaluate_relevance,
)
from app.services.routing_service import evaluate_and_persist_routing


@pytest.fixture(autouse=True)
def reset_caches():
    clear_embedding_cache()
    default_embedding_service.set_provider(DeterministicFakeEmbeddingProvider())
    yield
    clear_embedding_cache()
    default_embedding_service.set_provider(None)


def test_cosine_similarity_basic_properties():
    # Identical vectors
    v1 = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v1, v1) - 1.0) < 1e-6

    # Orthogonal vectors
    v2 = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(v1, v2) - 0.0) < 1e-6

    # Opposing vectors clamped to >= -1.0
    v3 = [-1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v1, v3) - (-1.0)) < 1e-6

    # Empty or mismatched vectors
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity(None, [1.0]) == 0.0


def test_exact_keyword_matches():
    provider = DeterministicFakeEmbeddingProvider()
    post_text = "maritime shipping and cargo at the port"
    post_emb = provider.embed_texts([post_text])[0]

    agent_interests = [
        Interest("keyword", "shipping"),
        Interest("keyword", "cargo"),
        Interest("keyword", "maritime"),
    ]
    agent_text = "shipping cargo maritime"
    agent_emb = provider.embed_texts([agent_text])[0]

    post = PostProfile(1, 99, "Shipping update", post_text, "shipping_logistics", embedding=post_emb)
    agent = AgentProfile(1, "SCI Agent", True, tuple(agent_interests), embedding=agent_emb)

    config = RelevanceConfig(threshold=0.25, top_k=5, deterministic_weight=0.60, semantic_weight=0.40)
    results = evaluate_relevance(post, [agent], config=config)
    result = results[0]

    assert result.eligible
    assert result.selected
    assert result.keyword_score == 1.0
    assert result.matched_keywords == ["cargo", "maritime", "shipping"]
    assert result.semantic_score > 0.70
    assert "keyword match" in result.explanation
    assert "semantic similarity" in result.explanation


def test_category_matches():
    post = PostProfile(1, 99, "Special Festive Discounts", "Discounts on items", "retail_promotion")
    agent = AgentProfile(1, "Flipkart Agent", True, (Interest("category", "retail_promotion"),))

    results = evaluate_relevance(post, [agent], config=RelevanceConfig(threshold=0.25))
    result = results[0]

    assert result.eligible
    assert result.selected
    assert result.category_score == 1.0
    assert result.matched_categories == ["retail_promotion"]
    assert "category match: retail_promotion" in result.explanation


def test_semantic_matches_with_different_wording():
    """Agent specifies 'shipping' and 'maritime', post uses different terminology 'vessels ocean freight transport'."""
    provider = DeterministicFakeEmbeddingProvider()
    post_text = "Ocean vessels freight transport dock arrival"
    post_emb = provider.embed_texts([post_text])[0]

    # Candidate has no matching keywords for 'ocean', 'vessels', 'arrival'
    agent_interests = [Interest("keyword", "shipping"), Interest("keyword", "maritime")]
    # But agent profile text contains conceptual synonyms in the same domain
    agent_text = "Maritime logistics and sea port cargo shipping operations"
    agent_emb = provider.embed_texts([agent_text])[0]

    post = PostProfile(1, 99, "Dock arrival", post_text, "news", embedding=post_emb)
    agent = AgentProfile(1, "SCI Agent", True, tuple(agent_interests), embedding=agent_emb)

    # Config: 0.40 deterministic, 0.60 semantic, threshold 0.20
    config = RelevanceConfig(
        threshold=0.20,
        top_k=5,
        deterministic_weight=0.40,
        semantic_weight=0.60,
        semantic_match_threshold=0.20,
    )
    results = evaluate_relevance(post, [agent], config=config)
    result = results[0]

    assert result.eligible
    assert result.selected
    # Keyword score is 0.0 because exact keywords didn't match
    assert result.keyword_score == 0.0
    # But semantic similarity is high due to the shared semantic cluster
    assert result.semantic_score >= 0.50
    assert result.final_score >= config.threshold
    assert "semantic similarity" in result.explanation


def test_relevant_paraphrases():
    """Paraphrased promotion matches food delivery agent."""
    provider = DeterministicFakeEmbeddingProvider()
    post_text = "Eatery dining promo: save 30% on weekend meal orders"
    post_emb = provider.embed_texts([post_text])[0]

    agent_interests = [Interest("category", "food_delivery"), Interest("keyword", "restaurants")]
    agent_text = "Restaurant dining cuisine food orders meal delivery"
    agent_emb = provider.embed_texts([agent_text])[0]

    post = PostProfile(2, 99, "Meal savings", post_text, "general", embedding=post_emb)
    agent = AgentProfile(2, "Swiggy Agent", True, tuple(agent_interests), embedding=agent_emb)

    results = evaluate_relevance(post, [agent], config=RelevanceConfig(threshold=0.20, semantic_match_threshold=0.20))
    result = results[0]

    assert result.eligible
    assert result.selected
    assert result.semantic_score > 0.40


def test_irrelevant_posts_with_similar_words():
    """Distinguish maritime 'port' from computer hardware 'port' via semantic embeddings."""
    provider = DeterministicFakeEmbeddingProvider()

    # Hardware text
    hardware_text = "Computer hardware network port 8080 configuration and software integration"
    hardware_emb = provider.embed_texts([hardware_text])[0]

    # Maritime agent has keyword 'port'
    agent_interests = [Interest("keyword", "port")]
    agent_text = "Maritime shipping dock harbor sea port logistics cargo"
    agent_emb = provider.embed_texts([agent_text])[0]

    post = PostProfile(3, 99, "Port setup", hardware_text, "tech", embedding=hardware_emb)
    agent = AgentProfile(3, "Maritime Agent", True, tuple(agent_interests), embedding=agent_emb)

    # With high semantic weight (0.70) and threshold (0.50), the irrelevant context suppresses the post
    config = RelevanceConfig(threshold=0.50, deterministic_weight=0.30, semantic_weight=0.70)
    results = evaluate_relevance(post, [agent], config=config)
    result = results[0]

    # Although "port" matched as a keyword (1 of 1 keyword -> keyword_score = 1.0)
    assert result.keyword_score == 1.0
    # But because it's a computer hardware post, semantic similarity is lower
    # and the resulting hybrid score (0.30 * 0.35 + 0.70 * sem) falls below the 0.50 threshold
    assert not result.selected
    assert "below threshold" in result.explanation


def test_blocked_companies_hard_exclusion():
    """Blocked relationships are hard exclusions that no semantic similarity can override."""
    provider = DeterministicFakeEmbeddingProvider()
    text = "Identical promotional announcement"
    emb = provider.embed_texts([text])[0]

    # Exactly identical embeddings -> cosine similarity = 1.0
    post = PostProfile(1, 10, "Announcement", text, "retail", embedding=emb)
    agent = AgentProfile(20, "Target Agent", True, (Interest("keyword", "promotional"),), embedding=emb)

    # Relationship block in source -> target direction
    results = evaluate_relevance(post, [agent], [Relationship(10, 20, "block")])
    assert not results[0].eligible
    assert not results[0].selected
    assert "hard exclusion" in results[0].explanation

    # Relationship block in target -> source direction (symmetric)
    results_sym = evaluate_relevance(post, [agent], [Relationship(20, 10, "block")])
    assert not results_sym[0].eligible
    assert "hard exclusion" in results_sym[0].explanation


def test_inactive_agents_hard_exclusion():
    """Inactive agents are excluded even with perfect semantic similarity."""
    provider = DeterministicFakeEmbeddingProvider()
    text = "Important payment update"
    emb = provider.embed_texts([text])[0]

    post = PostProfile(1, 99, "Update", text, "payments", embedding=emb)
    agent = AgentProfile(1, "Inactive Agent", False, (Interest("keyword", "payment"),), embedding=emb)

    results = evaluate_relevance(post, [agent])
    assert not results[0].eligible
    assert not results[0].selected
    assert "agent is inactive" in results[0].explanation


def test_explicit_exclusions_hard_exclusion():
    """Explicit exclusion terms disqualify candidates regardless of semantic score."""
    provider = DeterministicFakeEmbeddingProvider()
    text = "Confidential banking details and credit cards"
    emb = provider.embed_texts([text])[0]

    post = PostProfile(1, 99, "Title", text, "banking", embedding=emb)
    agent = AgentProfile(
        1, "Sensitive Agent", True,
        (Interest("keyword", "banking"), Interest("exclude", "confidential")),
        embedding=emb,
    )

    results = evaluate_relevance(post, [agent])
    assert not results[0].eligible
    assert "matched exclusion term: confidential" in results[0].explanation


def test_missing_embeddings_fallback():
    """When embeddings are None, the system falls back seamlessly to deterministic scoring."""
    post = PostProfile(1, 99, "Shopping deals", "Discounts on retail shopping", "retail_promotion", embedding=None)
    agent = AgentProfile(1, "Retail Agent", True, (Interest("category", "retail_promotion"),), embedding=None)

    config = RelevanceConfig(threshold=0.25, deterministic_weight=0.60, semantic_weight=0.40)
    results = evaluate_relevance(post, [agent], config=config)
    result = results[0]

    assert result.eligible
    assert result.selected
    assert result.semantic_score == 0.0
    # Final score equals deterministic score (0.55 * 1.0 = 0.55)
    assert result.final_score == 0.55
    assert result.deterministic_score == 0.55


def test_embedding_provider_failure_graceful_fallback():
    """If the embedding provider fails, the system logs and continues with deterministic scoring."""
    class FailingProvider(BaseEmbeddingProvider):
        @property
        def model_name(self) -> str:
            return "failing-model"

        def embed_texts(self, texts):
            raise EmbeddingProviderError("Simulated neural model crash / CUDA OOM")

    service = EmbeddingService(FailingProvider())
    batch = service.get_or_create_embeddings_batch(None, [("post", 1, "Some post text")])
    # Batch returns empty dict on failure without raising
    assert batch == {}


def test_hybrid_score_boundaries_and_configurable_weights():
    provider = DeterministicFakeEmbeddingProvider()
    text = "credit cards and banking offers"
    emb = provider.embed_texts([text])[0]

    post = PostProfile(1, 99, "Cards", text, "banking", embedding=emb)
    agent = AgentProfile(
        1, "Bank Agent", True,
        (Interest("category", "banking"), Interest("keyword", "credit cards")),
        embedding=emb,
    )

    # 1. 100% deterministic (weight = 1.0, 0.0)
    det_config = RelevanceConfig(threshold=0.25, deterministic_weight=1.0, semantic_weight=0.0)
    res_det = evaluate_relevance(post, [agent], config=det_config)[0]
    expected_det = 0.55 * 1.0 + 0.35 * 1.0  # 0.90
    assert abs(res_det.final_score - expected_det) < 1e-5

    # 2. 100% semantic (weight = 0.0, 1.0)
    sem_config = RelevanceConfig(threshold=0.25, deterministic_weight=0.0, semantic_weight=1.0)
    res_sem = evaluate_relevance(post, [agent], config=sem_config)[0]
    assert abs(res_sem.final_score - res_sem.semantic_score) < 1e-5

    # 3. 60/40 default hybrid formula
    hyb_config = RelevanceConfig(threshold=0.25, deterministic_weight=0.60, semantic_weight=0.40)
    res_hyb = evaluate_relevance(post, [agent], config=hyb_config)[0]
    expected_hyb = round(0.60 * expected_det + 0.40 * res_hyb.semantic_score, 6)
    assert abs(res_hyb.final_score - expected_hyb) < 1e-5

    # All component scores are bounded in [0.0, 1.0]
    assert 0.0 <= res_hyb.category_score <= 1.0
    assert 0.0 <= res_hyb.keyword_score <= 1.0
    assert 0.0 <= res_hyb.relationship_score <= 1.0
    assert 0.0 <= res_hyb.deterministic_score <= 1.0
    assert 0.0 <= res_hyb.semantic_score <= 1.0
    assert 0.0 <= res_hyb.final_score <= 1.0


def test_ranking_and_top_k_selection():
    """Verify that candidates are ranked by hybrid score descending, respecting top_k and tie-breaks."""
    provider = DeterministicFakeEmbeddingProvider()

    post_text = "Electronic gadgets discounts shopping"
    post_emb = provider.embed_texts([post_text])[0]
    post = PostProfile(1, 99, "Gadgets Sale", post_text, "retail_promotion", embedding=post_emb)

    # Agent A: High match (category + keywords + high semantic)
    emb_a = provider.embed_texts(["Electronics shopping discounts gadgets retail"])[0]
    agent_a = AgentProfile(10, "Agent A", True, (Interest("category", "retail_promotion"), Interest("keyword", "gadgets")), embedding=emb_a)

    # Agent B: Moderate match (keyword only)
    emb_b = provider.embed_texts(["Shopping deals promotion"])[0]
    agent_b = AgentProfile(20, "Agent B", True, (Interest("keyword", "shopping"),), embedding=emb_b)

    # Agent C: Low match (different keyword)
    emb_c = provider.embed_texts(["Food dining delivery"])[0]
    agent_c = AgentProfile(30, "Agent C", True, (Interest("keyword", "discounts"),), embedding=emb_c)

    # Agent D: Below threshold match
    agent_d = AgentProfile(40, "Agent D", True, (Interest("category", "other"),))

    # Evaluate with top_k = 2
    config = RelevanceConfig(threshold=0.20, top_k=2, deterministic_weight=0.60, semantic_weight=0.40)
    results = evaluate_relevance(post, [agent_a, agent_b, agent_c, agent_d], config=config)

    by_id = {r.agent_id: r for r in results}
    assert by_id[10].selected
    assert by_id[20].selected
    # Agent C is eligible but outside top_k
    assert by_id[30].eligible
    assert not by_id[30].selected
    assert "outside top_k" in by_id[30].explanation
    # Agent D is ineligible
    assert not by_id[40].eligible


def test_embedding_persistence_and_update_on_content_change():
    """Verify database caching and invalidation when content changes."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        service = EmbeddingService(DeterministicFakeEmbeddingProvider("test-model"))

        # 1. Initial generation stores row
        initial_vec = service.get_or_create_post_embedding(db, 101, "First Title", "news", "Initial content", entity_type="post")
        assert initial_vec is not None
        assert len(initial_vec) == 384

        row = db.scalar(select(StoredEmbedding).where(StoredEmbedding.entity_id == 101, StoredEmbedding.entity_type == "post"))
        assert row is not None
        assert row.embedding == initial_vec
        initial_hash = row.content_hash

        # 2. Calling again with unchanged content reuses cached/persisted vector
        same_vec = service.get_or_create_post_embedding(db, 101, "First Title", "news", "Initial content", entity_type="post")
        assert same_vec == initial_vec

        # 3. Content changes -> hash changes -> new embedding computed and persisted
        updated_vec = service.get_or_create_post_embedding(db, 101, "First Title", "news", "Brand new updated content", entity_type="post")
        db.refresh(row)
        assert row.content_hash != initial_hash
        assert row.embedding == updated_vec


def test_evaluate_and_persist_routing_end_to_end():
    """Verify end-to-end routing with database persistence of hybrid ScoringResult."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        # Create company and agents
        company = Company(name="Test Co", slug="test-co", status="active", network_opt_in=True)
        db.add(company)
        db.flush()

        agent_author = Agent(company_id=company.id, slug="author", company_name="Author Co", role="Writer", industry="news", description="Author", is_active=True)
        agent_target = Agent(company_id=company.id, slug="target", company_name="Target Co", role="Logistics", industry="shipping", description="Maritime shipping logistics", is_active=True)
        db.add_all([agent_author, agent_target])
        db.flush()

        db.add(AgentInterest(agent_id=agent_target.id, interest_type="keyword", value="maritime", weight=1.0))
        post = Post(
            company_id=company.id,
            author_agent_id=agent_author.id,
            title="Maritime freight",
            content="Maritime cargo vessel update at the port",
            category="shipping_logistics",
            content_hash="unique_hash_123",
        )
        db.add(post)
        db.commit()

        # Run routing
        results = evaluate_and_persist_routing(db, post)
        assert len(results) == 2  # author + target

        target_result = next(r for r in results if r.agent_id == agent_target.id)
        assert target_result.eligible
        assert target_result.selected
        assert target_result.semantic_score > 0.0

        # Verify persisted in RoutingDecision
        decision = db.scalar(select(RoutingDecision).where(RoutingDecision.post_id == post.id, RoutingDecision.agent_id == agent_target.id))
        assert decision is not None
        assert decision.selected is True
        assert decision.score == target_result.final_score
        assert decision.reason_json["semantic_score"] == target_result.semantic_score

        # Idempotent re-run returns stored decision without recomputing
        second_run = evaluate_and_persist_routing(db, post)
        assert [r.to_dict() for r in second_run] == [r.to_dict() for r in results]


def test_workspace_discovery_with_embeddings_and_network_opt_out():
    """Verify workspace discovery end-to-end: hybrid signals, StoredEmbedding creation, and opt-out exclusion."""
    from app.services.workspace import Principal, discover
    from app.db.network import RuntimeMutex, User

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db:
        # Initialize runtime mutex for lock_runtime
        db.add(RuntimeMutex(id=1, value=0))
        user = User(email="author@example.test", name="Author", password_hash="hash", status="active")
        db.add(user)
        db.flush()

        from app.services.security import create_company
        company_a = create_company(db, user, "Co A", "co-a")
        company_a.network_opt_in = True
        company_b = create_company(db, user, "Co B", "co-b")
        company_b.network_opt_in = True
        company_hidden = create_company(db, user, "Hidden Co", "co-hidden")
        company_hidden.network_opt_in = False
        db.flush()

        agent_source = Agent(company_id=company_a.id, slug="source-agent", company_name="Co A", role="Publisher", industry="news", description="Publishes updates", is_active=True)
        agent_target = Agent(company_id=company_b.id, slug="target-agent", company_name="Co B", role="Buyer", industry="retail", description="Retail shopping promotions", is_active=True)
        agent_opted_out = Agent(company_id=company_hidden.id, slug="hidden-agent", company_name="Hidden Co", role="Private", industry="finance", description="Private finance", is_active=True)
        db.add_all([agent_source, agent_target, agent_opted_out])
        db.flush()

        account_src = AgentAccount(id=agent_source.id, company_id=company_a.id, slug="source-agent", state="active")
        account_tgt = AgentAccount(id=agent_target.id, company_id=company_b.id, slug="target-agent", state="active")
        account_hid = AgentAccount(id=agent_opted_out.id, company_id=company_hidden.id, slug="hidden-agent", state="active")
        db.add_all([account_src, account_tgt, account_hid])
        db.flush()

        cfg_src = {"name": "Source Agent", "allow_public": True, "discoverable": True, "categories": ["retail_promotion"]}
        cfg_tgt = {"name": "Target Agent", "allow_public": True, "discoverable": True, "categories": ["retail_promotion"], "keywords": ["shopping"]}
        cfg_hid = {"name": "Hidden Agent", "allow_public": True, "discoverable": True, "categories": ["retail_promotion"]}

        v_src = AgentVersion(agent_id=account_src.id, version=1, config=cfg_src, created_by=user.id)
        v_tgt = AgentVersion(agent_id=account_tgt.id, version=1, config=cfg_tgt, created_by=user.id)
        v_hid = AgentVersion(agent_id=account_hid.id, version=1, config=cfg_hid, created_by=user.id)
        db.add_all([v_src, v_tgt, v_hid])
        db.flush()

        account_src.active_version_id = v_src.id
        account_tgt.active_version_id = v_tgt.id
        account_hid.active_version_id = v_hid.id

        pub = Publication(
            company_id=company_a.id,
            author_type="agent",
            agent_id=account_src.id,
            title="Retail Super Sale",
            content="Discounts and shopping offers on retail items",
            category="retail_promotion",
            visibility="network",
            status="published",
            idempotency_key="pub-100",
            content_hash="hash_pub_100",
            policy_version=1,
            published_at=datetime.now(timezone.utc),
        )
        db.add(pub)
        db.commit()

        principal = Principal(user, company_a, "")
        records = discover(db, principal, pub)

        tgt_rec = next(r for r in records if r.agent_id == account_tgt.id)
        assert tgt_rec.eligible is True
        assert tgt_rec.selected is True
        assert tgt_rec.signals["hybrid"] == tgt_rec.score
        assert "deterministic" in tgt_rec.signals
        assert "semantic" in tgt_rec.signals

        hid_rec = next(r for r in records if r.agent_id == account_hid.id)
        assert hid_rec.eligible is False
        assert hid_rec.selected is False
        assert "Excluded by network authorization or lifecycle policy" in hid_rec.explanation

        # Verify stored embeddings were created
        emb_pub = db.scalar(select(StoredEmbedding).where(StoredEmbedding.entity_id == pub.id, StoredEmbedding.entity_type == "publication"))
        assert emb_pub is not None
        assert len(emb_pub.embedding) == 384
