from fastapi.testclient import TestClient


def investor_payload() -> dict[str, object]:
    return {
        "name": "Long Horizon Investor",
        "base_currency": "usd",
        "investment_horizon_years": 15,
        "liquidity_need": 0.1,
        "objectives": "Preserve purchasing power and compound patiently.",
        "constraints": "No leverage.",
        "risk_profile": {
            "tolerance": "moderate",
            "max_drawdown": 0.2,
            "loss_capacity": 0.25,
            "notes": "Drawdown tolerance reviewed annually.",
            "risk_budget": {
                "total_risk_budget": 0.15,
                "per_decision_limit": 0.03,
                "minimum_cash_allocation": 0.1,
            },
        },
    }


def test_create_and_get_investor_profile(client: TestClient) -> None:
    created = client.post("/api/v1/investors", json=investor_payload())

    assert created.status_code == 201
    body = created.json()
    assert body["base_currency"] == "USD"
    assert body["risk_profile"]["risk_budget"]["minimum_cash_allocation"] == "0.100000"

    fetched = client.get(f"/api/v1/investors/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_risk_budget_rejects_per_decision_limit_above_total(client: TestClient) -> None:
    payload = investor_payload()
    risk_profile = payload["risk_profile"]
    assert isinstance(risk_profile, dict)
    risk_budget = risk_profile["risk_budget"]
    assert isinstance(risk_budget, dict)
    risk_budget["per_decision_limit"] = 0.2

    response = client.post("/api/v1/investors", json=payload)

    assert response.status_code == 422


def test_missing_investor_returns_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/investors/999")
    assert response.status_code == 404
