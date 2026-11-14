from app.services.relevance import (
    AgentProfile, Interest, PostProfile, Relationship, RelevanceConfig, evaluate_relevance,
)


def agent(agent_id, interests=(), active=True):
    return AgentProfile(agent_id, f"Agent {agent_id}", active, tuple(interests))


def post(author=99, title="Update", content="A maritime cargo update at the ports.", category="news"):
    return PostProfile(1, author, title, content, category)


def test_category_match_scores_and_explains():
    result = evaluate_relevance(
        post(category="retail_promotion"),
        [agent(1, [Interest("category", "retail_promotion")])],
    )[0]
    assert result.category_score == 1
    assert result.final_score == 0.55
    assert result.matched_categories == ["retail_promotion"]
    assert result.selected
    assert "topical relevance found" in result.explanation


def test_keyword_match_uses_normalized_phrases_and_synonyms():
    results = evaluate_relevance(
        post(content="A CREDIT CARD bank offer.", category="news"),
        [agent(1, [
            Interest("keyword", "credit cards"),
            Interest("keyword", "banking offers"),
            Interest("keyword", "art"),
        ])],
        config=RelevanceConfig(threshold=0.2),
    )
    result = results[0]
    assert result.matched_keywords == ["banking offers", "credit cards"]
    assert abs(result.keyword_score - (2 / 3)) < 0.000001
    assert result.selected


def test_keyword_phrase_does_not_match_substring():
    result = evaluate_relevance(
        post(content="A cart is on the road.", category="news"),
        [agent(1, [Interest("keyword", "art")])],
    )[0]
    assert result.matched_keywords == []
    assert not result.eligible


def test_no_interest_agent_is_excluded():
    result = evaluate_relevance(post(), [agent(1)])[0]
    assert not result.eligible
    assert "no configured interests" in result.explanation


def test_author_inactive_and_exclusion_terms_are_excluded():
    results = evaluate_relevance(
        post(author=1, content="Sensitive shipping and cargo update."),
        [
            agent(1, [Interest("keyword", "shipping")]),
            agent(2, [Interest("keyword", "shipping")], active=False),
            agent(3, [Interest("keyword", "shipping"), Interest("exclude", "sensitive")]),
        ],
    )
    assert all(not result.eligible for result in results)
    assert "post author" in results[0].explanation
    assert "inactive" in results[1].explanation
    assert "exclusion term" in results[2].explanation


def test_block_is_hard_exclusion_in_either_direction():
    result = evaluate_relevance(
        post(author=9),
        [agent(1, [Interest("keyword", "maritime")])],
        [Relationship(1, 9, "block")],
    )[0]
    assert not result.eligible
    assert "hard exclusion" in result.explanation


def test_relationship_alone_cannot_make_agent_topically_eligible():
    result = evaluate_relevance(
        post(content="Unrelated content.", category="other"),
        [agent(1, [Interest("keyword", "maritime")])],
        [Relationship(99, 1, "partner", 1.0)],
    )[0]
    assert result.relationship_score == 1
    assert not result.eligible
    assert not result.selected
    assert result.final_score == 0.1


def test_threshold_applied_after_scoring():
    result = evaluate_relevance(
        post(category="news"),
        [agent(1, [Interest("category", "news")])],
        config=RelevanceConfig(threshold=0.56, top_k=5),
    )[0]
    assert result.final_score == 0.55
    assert result.eligible
    assert not result.selected
    assert "below threshold" in result.explanation


def test_threshold_uses_unrounded_score_at_boundary():
    result = evaluate_relevance(
        post(content="maritime only", category="news"),
        [agent(1, [
            Interest("keyword", "maritime"),
            Interest("keyword", "aviation"),
            Interest("keyword", "railway"),
        ])],
        config=RelevanceConfig(threshold=0.1166667, top_k=5),
    )[0]
    assert result.final_score == 0.116667
    assert not result.selected
    assert "below threshold" in result.explanation


def test_partner_boost_is_normalized_and_requires_topical_match():
    result = evaluate_relevance(
        post(content="maritime cargo news"),
        [agent(1, [Interest("keyword", "maritime")])],
        [Relationship(99, 1, "partner", 4.0)],
    )[0]
    assert result.relationship_score == 1
    assert result.selected
    assert result.final_score == 0.45


def test_partner_relationship_is_symmetric_for_mvp():
    for relationship in (Relationship(1, 99, "partner", 0.5), Relationship(99, 1, "partner", 0.5)):
        result = evaluate_relevance(
            post(content="maritime cargo update"),
            [agent(1, [Interest("keyword", "maritime")])],
            [relationship],
        )[0]
        assert result.relationship_score == 0.5


def test_block_relationship_is_symmetric_for_mvp():
    for relationship in (Relationship(1, 99, "block"), Relationship(99, 1, "block")):
        result = evaluate_relevance(
            post(content="maritime cargo update"),
            [agent(1, [Interest("keyword", "maritime")])],
            [relationship],
        )[0]
        assert not result.eligible
        assert "hard exclusion" in result.explanation


def test_top_k_and_tie_break_are_deterministic_by_agent_id():
    results = evaluate_relevance(
        post(category="news"),
        [
            agent(8, [Interest("category", "news")]),
            agent(2, [Interest("category", "news")]),
            agent(5, [Interest("category", "news")]),
        ],
        config=RelevanceConfig(threshold=0.25, top_k=2),
    )
    selected = [row.agent_id for row in results if row.selected]
    assert selected == [2, 5]
    assert "outside top_k" in next(row.explanation for row in results if row.agent_id == 8)
