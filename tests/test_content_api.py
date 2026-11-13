from fastapi.testclient import TestClient

ARTICLE = {
    "slug": "macro-research-note",
    "title_fa": "یادداشت پژوهش کلان",
    "dek_fa": "نمونهٔ محتوای تحریریه برای آزمون انتشار.",
    "body_fa": "این متن فقط برای آزمون قرارداد انتشار است و هیچ توصیهٔ معاملاتی ارائه نمی‌کند.",
    "category": "macro",
    "author_display_name": "تحریریه MacroVision",
}


def test_draft_is_not_public_until_explicit_publication(client: TestClient) -> None:
    created = client.post("/api/v1/content/articles", json=ARTICLE)
    assert created.status_code == 201
    article_id = created.json()["id"]
    assert client.get("/api/v1/public/content/articles/macro-research-note").status_code == 404

    published = client.post(
        f"/api/v1/content/articles/{article_id}/publish",
        json={"published_at": "2026-01-01T00:00:00Z"},
    )
    assert published.status_code == 200
    public = client.get("/api/v1/public/content/articles/macro-research-note")
    assert public.status_code == 200
    assert public.json()["slug"] == "macro-research-note"
    assert "id" not in public.json()
    assert "status" not in public.json()


def test_future_publication_is_not_visible(client: TestClient) -> None:
    payload = {**ARTICLE, "slug": "future-note"}
    created = client.post("/api/v1/content/articles", json=payload)
    article_id = created.json()["id"]
    published = client.post(
        f"/api/v1/content/articles/{article_id}/publish",
        json={"published_at": "2099-01-01T00:00:00Z"},
    )
    assert published.status_code == 200
    assert client.get("/api/v1/public/content/articles/future-note").status_code == 404
    page = client.get("/api/v1/public/content/articles")
    assert page.status_code == 200
    assert all(item["slug"] != "future-note" for item in page.json()["items"])


def test_subscription_requires_consent_and_unsubscribe_is_idempotent(client: TestClient) -> None:
    denied = client.post(
        "/api/v1/public/subscriptions",
        json={"email": "reader@example.com", "consent": False},
    )
    assert denied.status_code == 422
    created = client.post(
        "/api/v1/public/subscriptions",
        json={"email": " Reader@Example.com ", "consent": True},
    )
    assert created.status_code == 201
    token = created.json()["unsubscribe_token"]
    assert len(token) >= 32
    for _ in range(2):
        response = client.post(
            "/api/v1/public/subscriptions/unsubscribe",
            json={"token": token},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "unsubscribed"}


def test_invalid_email_and_duplicate_slug_fail_closed(client: TestClient) -> None:
    invalid = client.post(
        "/api/v1/public/subscriptions",
        json={"email": "not-an-email", "consent": True},
    )
    assert invalid.status_code == 422
    assert client.post("/api/v1/content/articles", json=ARTICLE).status_code == 201
    duplicate = client.post("/api/v1/content/articles", json=ARTICLE)
    assert duplicate.status_code == 409
