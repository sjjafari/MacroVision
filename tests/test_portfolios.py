from decimal import Decimal
from pathlib import Path
from typing import Any, TypedDict, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from macrovision import portfolio_models, portfolio_schemas, portfolio_services


class PortfolioJson(TypedDict):
    id: int
    base_currency: str
    positions: list[dict[str, Any]]
    cash_balances: list[dict[str, Any]]


def create_portfolio(client: TestClient, name: str = "Core Portfolio") -> PortfolioJson:
    response = client.post(
        "/api/v1/portfolios",
        json={"name": name, "base_currency": "usd"},
    )
    assert response.status_code == 201
    return cast(PortfolioJson, response.json())


def record(
    client: TestClient,
    portfolio_id: int,
    transaction_type: str,
    **fields: object,
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        json={"transaction_type": transaction_type, "currency": "USD", **fields},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_create_list_and_retrieve_portfolios(client: TestClient) -> None:
    first = create_portfolio(client)
    second = create_portfolio(client, "Opportunity Portfolio")

    portfolios = client.get("/api/v1/portfolios")
    assert portfolios.status_code == 200
    assert [item["id"] for item in portfolios.json()] == [first["id"], second["id"]]
    assert first["base_currency"] == "USD"
    assert first["positions"] == []
    assert first["cash_balances"] == []

    fetched = client.get(f"/api/v1/portfolios/{first['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == first
    assert client.get("/api/v1/portfolios/999").status_code == 404

    missing_investor = client.post(
        "/api/v1/portfolios",
        json={"name": "Invalid owner", "base_currency": "USD", "investor_id": 999},
    )
    assert missing_investor.status_code == 404


def test_buy_weighted_cost_price_update_and_summary(client: TestClient) -> None:
    portfolio = create_portfolio(client)
    portfolio_id = portfolio["id"]
    record(client, portfolio_id, "deposit", amount="2000.00")
    record(
        client,
        portfolio_id,
        "buy",
        symbol="mv",
        asset_name="MacroVision Fund",
        quantity="10",
        unit_price="100",
    )
    record(
        client,
        portfolio_id,
        "buy",
        symbol="MV",
        quantity="5",
        unit_price="160",
    )

    fetched = client.get(f"/api/v1/portfolios/{portfolio_id}").json()
    position = fetched["positions"][0]
    assert position["quantity"] == "15.0000000000"
    assert position["average_cost"] == "120.00000000"
    assert position["cost_basis"] == "1800.00000000"
    assert fetched["cash_balances"][0]["balance"] == "200.00000000"

    updated = client.put(
        f"/api/v1/portfolios/{portfolio_id}/positions/{position['id']}/price",
        json={"current_price": "150.00"},
    )
    assert updated.status_code == 200
    updated_position = updated.json()["positions"][0]
    assert updated_position["market_value"] == "2250.00000000"
    assert updated_position["unrealized_pl"] == "450.00000000"

    summary = client.get(f"/api/v1/portfolios/{portfolio_id}/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_value"] == "2450.00000000"
    assert body["total_cost_basis"] == "1800.00000000"
    assert Decimal(body["allocations"]["MV"]) + Decimal(body["allocations"]["CASH"]) == Decimal(
        "100"
    )


def test_partial_sell_preserves_weighted_average_cost(client: TestClient) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="1000")
    record(client, portfolio_id, "buy", symbol="MV", quantity="3", unit_price="10")
    record(client, portfolio_id, "buy", symbol="MV", quantity="2", unit_price="20")
    record(client, portfolio_id, "sell", symbol="MV", quantity="1.5", unit_price="25")

    position = client.get(f"/api/v1/portfolios/{portfolio_id}").json()["positions"][0]
    assert position["quantity"] == "3.5000000000"
    assert position["average_cost"] == "14.00000000"
    assert position["realized_pl"] == "16.50000000"


def test_weighted_average_uses_explicit_half_even_rounding(client: TestClient) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="3")
    record(client, portfolio_id, "buy", symbol="MV", quantity="1", unit_price="1.00000000")
    record(client, portfolio_id, "buy", symbol="MV", quantity="1", unit_price="1.00000001")

    position = client.get(f"/api/v1/portfolios/{portfolio_id}").json()["positions"][0]
    assert position["average_cost"] == "1.00000000"


def test_allocation_rounding_totals_exactly_one_hundred(client: TestClient) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="300")
    for symbol in ("AAA", "BBB", "CCC"):
        record(client, portfolio_id, "buy", symbol=symbol, quantity="1", unit_price="100")

    allocations = client.get(f"/api/v1/portfolios/{portfolio_id}/summary").json()["allocations"]
    assert sum(map(Decimal, allocations.values())) == Decimal("100.00000000")
    assert allocations["CCC"] == "33.33333334"


def test_cash_transactions_and_foreign_cash_are_separate(client: TestClient) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="1000")
    record(client, portfolio_id, "dividend", amount="25", symbol="MV")
    record(client, portfolio_id, "interest", amount="5")
    record(client, portfolio_id, "withdrawal", amount="100")
    record(client, portfolio_id, "fee", amount="10")
    foreign = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        json={"transaction_type": "deposit", "currency": "EUR", "amount": "50"},
    )
    assert foreign.status_code == 201

    summary = client.get(f"/api/v1/portfolios/{portfolio_id}/summary").json()
    assert summary["base_cash_balance"] == "920.00000000"
    assert summary["total_value"] == "920.00000000"
    assert summary["cash_balances"] == {"EUR": "50.00000000", "USD": "920.00000000"}
    assert summary["unconverted_cash_currencies"] == ["EUR"]

    transactions = client.get(f"/api/v1/portfolios/{portfolio_id}/transactions")
    assert transactions.status_code == 200
    assert [item["transaction_type"] for item in transactions.json()] == [
        "deposit",
        "dividend",
        "interest",
        "withdrawal",
        "fee",
        "deposit",
    ]
    assert transactions.json()[4]["realized_pl"] == "-10.00000000"
    assert summary["realized_pl"] == "-10.00000000"


def test_fee_reduces_cash_and_realized_pl_but_not_position_cost_basis(
    client: TestClient,
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="1000")
    record(client, portfolio_id, "buy", symbol="MV", quantity="5", unit_price="100")
    record(client, portfolio_id, "fee", amount="10", symbol="MV")

    summary = client.get(f"/api/v1/portfolios/{portfolio_id}/summary").json()
    assert summary["base_cash_balance"] == "490.00000000"
    assert summary["total_cost_basis"] == "500.00000000"
    assert summary["realized_pl"] == "-10.00000000"
    assert summary["total_value"] == "990.00000000"


def test_sell_realizes_profit_and_full_sale_removes_position(client: TestClient) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="2000")
    record(client, portfolio_id, "buy", symbol="MV", quantity="10", unit_price="100")
    partial = record(client, portfolio_id, "sell", symbol="MV", quantity="4", unit_price="125")
    assert partial["realized_pl"] == "100.00000000"

    portfolio = client.get(f"/api/v1/portfolios/{portfolio_id}").json()
    assert portfolio["positions"][0]["quantity"] == "6.0000000000"
    assert portfolio["positions"][0]["realized_pl"] == "100.00000000"

    final_sale = record(client, portfolio_id, "sell", symbol="MV", quantity="6", unit_price="90")
    assert final_sale["realized_pl"] == "-60.00000000"
    portfolio = client.get(f"/api/v1/portfolios/{portfolio_id}").json()
    assert portfolio["positions"] == []
    summary = client.get(f"/api/v1/portfolios/{portfolio_id}/summary").json()
    assert summary["realized_pl"] == "40.00000000"
    assert summary["base_cash_balance"] == "2040.00000000"
    transactions = client.get(f"/api/v1/portfolios/{portfolio_id}/transactions").json()
    assert len(transactions) == 4
    assert [transaction["realized_pl"] for transaction in transactions[-2:]] == [
        "100.00000000",
        "-60.00000000",
    ]


@pytest.mark.parametrize(
    ("setup", "payload", "expected_detail"),
    [
        (
            [],
            {"transaction_type": "withdrawal", "currency": "USD", "amount": "1"},
            "Insufficient USD cash",
        ),
        (
            [
                ("deposit", {"amount": "100"}),
                ("buy", {"symbol": "MV", "quantity": "1", "unit_price": "50"}),
            ],
            {
                "transaction_type": "sell",
                "currency": "USD",
                "symbol": "MV",
                "quantity": "2",
                "unit_price": "60",
            },
            "Cannot sell more than",
        ),
        (
            [("deposit", {"amount": "100"})],
            {
                "transaction_type": "buy",
                "currency": "EUR",
                "symbol": "MV",
                "quantity": "1",
                "unit_price": "50",
            },
            "base currency",
        ),
    ],
)
def test_invalid_accounting_operations_are_rejected(
    client: TestClient,
    setup: list[tuple[str, dict[str, str]]],
    payload: dict[str, str],
    expected_detail: str,
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    for transaction_type, fields in setup:
        record(client, portfolio_id, transaction_type, **fields)

    response = client.post(f"/api/v1/portfolios/{portfolio_id}/transactions", json=payload)
    assert response.status_code == 409
    assert expected_detail in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"transaction_type": "buy", "currency": "USD", "symbol": "MV"},
        {"transaction_type": "deposit", "currency": "USD"},
        {
            "transaction_type": "fee",
            "currency": "USD",
            "amount": "1",
            "quantity": "1",
        },
        {
            "transaction_type": "buy",
            "currency": "USD",
            "symbol": "MV",
            "quantity": "1",
            "unit_price": "1",
            "amount": "1",
        },
    ],
)
def test_transaction_shape_validation(client: TestClient, payload: dict[str, str]) -> None:
    portfolio_id = create_portfolio(client)["id"]
    response = client.post(f"/api/v1/portfolios/{portfolio_id}/transactions", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {
            "transaction_type": "deposit",
            "currency": "USD",
            "amount": "0",
        },
        {
            "transaction_type": "deposit",
            "currency": "USD",
            "amount": "-1",
        },
        {
            "transaction_type": "buy",
            "currency": "USD",
            "symbol": "MV",
            "quantity": "0",
            "unit_price": "1",
        },
        {
            "transaction_type": "buy",
            "currency": "USD",
            "symbol": "MV",
            "quantity": "1",
            "unit_price": "-1",
        },
        {
            "transaction_type": "deposit",
            "currency": "US1",
            "amount": "1",
        },
        {
            "transaction_type": "buy",
            "currency": "USD",
            "symbol": "CASH",
            "quantity": "1",
            "unit_price": "1",
        },
    ],
)
def test_zero_negative_and_malformed_financial_requests_are_rejected(
    client: TestClient, payload: dict[str, str]
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    assert (
        client.post(f"/api/v1/portfolios/{portfolio_id}/transactions", json=payload).status_code
        == 422
    )


def test_snapshots_are_timestamped_and_preserve_point_in_time_values(
    client: TestClient,
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="1000")
    record(client, portfolio_id, "buy", symbol="MV", quantity="5", unit_price="100")
    portfolio = client.get(f"/api/v1/portfolios/{portfolio_id}").json()
    position_id = portfolio["positions"][0]["id"]

    first = client.post(f"/api/v1/portfolios/{portfolio_id}/snapshots")
    assert first.status_code == 201
    assert first.json()["total_value"] == "1000.00000000"

    client.put(
        f"/api/v1/portfolios/{portfolio_id}/positions/{position_id}/price",
        json={"current_price": "120"},
    )
    second = client.post(f"/api/v1/portfolios/{portfolio_id}/snapshots")
    assert second.status_code == 201
    assert second.json()["total_value"] == "1100.00000000"

    snapshots = client.get(f"/api/v1/portfolios/{portfolio_id}/snapshots")
    assert snapshots.status_code == 200
    assert [item["total_value"] for item in snapshots.json()] == [
        "1000.00000000",
        "1100.00000000",
    ]


def test_transaction_rows_are_immutable(db_session: Session) -> None:
    portfolio = portfolio_services.create_portfolio(
        db_session, portfolio_schemas.PortfolioCreate(name="Audit", base_currency="USD")
    )
    transaction = portfolio_services.record_transaction(
        db_session,
        portfolio.id,
        portfolio_schemas.TransactionCreate(
            transaction_type=portfolio_models.TransactionType.deposit,
            amount=Decimal("100"),
            currency="USD",
        ),
    )
    transaction.note = "attempted rewrite"
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    db_session.delete(transaction)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_snapshot_rows_are_immutable(db_session: Session) -> None:
    portfolio = portfolio_services.create_portfolio(
        db_session, portfolio_schemas.PortfolioCreate(name="Snapshot audit")
    )
    snapshot = portfolio_services.create_snapshot(db_session, portfolio.id)
    snapshot.total_value = Decimal("1")
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    db_session.delete(snapshot)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_failed_transaction_rolls_back_cash_position_and_transaction(
    client: TestClient, db_session: Session
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    record(client, portfolio_id, "deposit", amount="100")

    failed = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        json={
            "transaction_type": "buy",
            "currency": "USD",
            "symbol": "MV",
            "quantity": "2",
            "unit_price": "60",
        },
    )
    assert failed.status_code == 409

    db_session.expire_all()
    portfolio = portfolio_services.get_portfolio(db_session, portfolio_id)
    assert portfolio.positions == []
    assert [(cash.currency, cash.balance) for cash in portfolio.cash_balances] == [
        ("USD", Decimal("100.00000000"))
    ]
    assert [transaction.transaction_type for transaction in portfolio.transactions] == [
        portfolio_models.TransactionType.deposit
    ]


def test_exact_scaled_integer_round_trip_and_overflow_rejection(
    client: TestClient, db_session: Session
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    exact_amount = "1234567890.12345678"
    record(client, portfolio_id, "deposit", amount=exact_amount)

    db_session.expire_all()
    portfolio = portfolio_services.get_portfolio(db_session, portfolio_id)
    assert portfolio.cash_balances[0].balance == Decimal(exact_amount)
    raw_balance = db_session.execute(
        text("SELECT balance FROM cash_balances WHERE portfolio_id = :portfolio_id"),
        {"portfolio_id": portfolio_id},
    ).scalar_one()
    assert raw_balance == 123456789012345678

    overflow = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        json={
            "transaction_type": "deposit",
            "currency": "USD",
            "amount": "92233720368.54775807",
        },
    )
    assert overflow.status_code == 409
    assert "storage range" in overflow.json()["detail"]
    db_session.expire_all()
    assert portfolio_services.get_portfolio(db_session, portfolio_id).cash_balances[
        0
    ].balance == Decimal(exact_amount)


def test_database_foreign_keys_indexes_and_audit_history_restriction(
    db_session: Session,
) -> None:
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    portfolio = portfolio_services.create_portfolio(
        db_session, portfolio_schemas.PortfolioCreate(name="Integrity")
    )
    portfolio_services.record_transaction(
        db_session,
        portfolio.id,
        portfolio_schemas.TransactionCreate(
            transaction_type=portfolio_models.TransactionType.deposit,
            amount=Decimal("100"),
        ),
    )
    portfolio_services.create_snapshot(db_session, portfolio.id)

    with pytest.raises(IntegrityError):
        db_session.execute(
            delete(portfolio_models.Portfolio).where(portfolio_models.Portfolio.id == portfolio.id)
        )
    db_session.rollback()

    database_inspector = inspect(db_session.get_bind())
    transaction_indexes = {
        tuple(index["column_names"])
        for index in database_inspector.get_indexes("portfolio_transactions")
    }
    snapshot_indexes = {
        tuple(index["column_names"])
        for index in database_inspector.get_indexes("portfolio_snapshots")
    }
    assert ("portfolio_id", "occurred_at") in transaction_indexes
    assert ("portfolio_id", "symbol") in transaction_indexes
    assert ("portfolio_id", "captured_at") in snapshot_indexes


def test_zero_value_summary_and_api_surface_match_documented_contract(
    client: TestClient,
) -> None:
    portfolio_id = create_portfolio(client)["id"]
    summary = client.get(f"/api/v1/portfolios/{portfolio_id}/summary")
    assert summary.status_code == 200
    assert summary.json()["total_value"] == "0E-8"
    assert summary.json()["allocations"] == {}

    paths = client.get("/openapi.json").json()["paths"]
    expected_paths = {
        "/api/v1/portfolios",
        "/api/v1/portfolios/{portfolio_id}",
        "/api/v1/portfolios/{portfolio_id}/transactions",
        "/api/v1/portfolios/{portfolio_id}/positions/{position_id}/price",
        "/api/v1/portfolios/{portfolio_id}/summary",
        "/api/v1/portfolios/{portfolio_id}/snapshots",
    }
    assert expected_paths <= set(paths)
    readme = Path("README.md").read_text(encoding="utf-8")
    for path in expected_paths:
        assert path in readme
    assert client.delete(f"/api/v1/portfolios/{portfolio_id}/transactions/999").status_code == 404


def test_missing_portfolio_resources_return_not_found(client: TestClient) -> None:
    assert client.get("/api/v1/portfolios/999/transactions").status_code == 404
    assert client.get("/api/v1/portfolios/999/snapshots").status_code == 404
    assert client.get("/api/v1/portfolios/999/summary").status_code == 404
    assert client.post("/api/v1/portfolios/999/snapshots").status_code == 404
    assert (
        client.put(
            "/api/v1/portfolios/999/positions/1/price",
            json={"current_price": "1"},
        ).status_code
        == 404
    )


def test_missing_position_and_sell_position_are_rejected(client: TestClient) -> None:
    portfolio_id = create_portfolio(client)["id"]
    missing_price = client.put(
        f"/api/v1/portfolios/{portfolio_id}/positions/999/price",
        json={"current_price": "10"},
    )
    assert missing_price.status_code == 404

    missing_sell = client.post(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        json={
            "transaction_type": "sell",
            "currency": "USD",
            "symbol": "NONE",
            "quantity": "1",
            "unit_price": "10",
        },
    )
    assert missing_sell.status_code == 409
