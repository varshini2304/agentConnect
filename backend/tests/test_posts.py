def post_payload(author_id, **overrides):
    value = {
        "author_agent_id": author_id,
        "title": "  A useful   update ",
        "content": "Line one.\n  Line two. ",
        "category": "News",
    }
    value.update(overrides)
    return value


def agent_id(client, slug="swiggy"):
    return next(agent["id"] for agent in client.get("/api/agents").json() if agent["slug"] == slug)


def test_create_post_normalizes_content_and_includes_author(client):
    response = client.post("/api/posts", json=post_payload(agent_id(client)))
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "A useful update"
    assert data["content"] == "Line one. Line two."
    assert data["category"] == "news"
    assert data["author"]["slug"] == "swiggy"
    assert data["created_at"]


def test_invalid_post_rejected(client):
    assert client.post("/api/posts", json=post_payload(agent_id(client), title="  ")).status_code == 422


def test_duplicate_post_returns_existing_record(client):
    author_id = agent_id(client)
    first = client.post("/api/posts", json=post_payload(author_id))
    duplicate = client.post("/api/posts", json=post_payload(
        author_id, title="a useful update", content="Line one. Line two.", category="news"
    ))
    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == first.json()["id"]


def test_different_authors_can_publish_identical_text_independently(client):
    first = client.post("/api/posts", json=post_payload(agent_id(client)))
    second = client.post("/api/posts", json=post_payload(agent_id(client, "phonepe")))
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_feed_newest_first_and_pagination(client):
    author = agent_id(client)
    client.post("/api/posts", json=post_payload(author, title="First", content="one"))
    client.post("/api/posts", json=post_payload(author, title="Second", content="two"))
    response = client.get("/api/posts?limit=1&offset=0")
    assert response.status_code == 200
    assert response.json()["limit"] == 1
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["title"] == "Second"


def test_post_detail_and_unknown_post(client):
    post = client.post("/api/posts", json=post_payload(agent_id(client))).json()
    assert client.get(f"/api/posts/{post['id']}").status_code == 200
    assert client.get("/api/posts/999999").status_code == 404


def test_unknown_author_cannot_publish(client):
    assert client.post("/api/posts", json=post_payload(999999)).status_code == 404
