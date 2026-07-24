import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from macrovision import models as core_models
from macrovision import portfolio_models as models
from macrovision import portfolio_schemas as schemas
from macrovision.integrity import IntegrityConflictError, commit_or_conflict

ZERO = Decimal("0")
PERCENT = Decimal("100")
MONEY_QUANTUM = Decimal("0.00000001")
QUANTITY_QUANTUM = Decimal("0.0000000001")
MAX_MONEY = schemas.MAX_MONEY
MAX_QUANTITY = schemas.MAX_QUANTITY


def _money(value: Decimal) -> Decimal:
    rounded = value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if abs(rounded) > MAX_MONEY:
        raise PortfolioDomainError("Calculated financial value exceeds storage range")
    return rounded


def _quantity(value: Decimal) -> Decimal:
    rounded = value.quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_EVEN)
    if rounded > MAX_QUANTITY:
        raise PortfolioDomainError("Calculated position quantity exceeds storage range")
    return rounded


def _utc_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioDomainError("Timestamp must include a UTC offset")
    return value.astimezone(UTC)


class PortfolioNotFoundError(Exception):
    pass


class PortfolioDomainError(Exception):
    pass


def _mark_mutated(portfolio: models.Portfolio) -> None:
    portfolio.lock_version += 1


def _verify_accounting_invariants(portfolio: models.Portfolio) -> None:
    if any(balance.balance < ZERO for balance in portfolio.cash_balances):
        raise PortfolioDomainError("Portfolio cash balance cannot be negative")
    if any(position.quantity <= ZERO for position in portfolio.positions):
        raise PortfolioDomainError("Portfolio position quantity must remain positive")


def _portfolio_statement() -> Select[tuple[models.Portfolio]]:
    return select(models.Portfolio).options(
        selectinload(models.Portfolio.positions),
        selectinload(models.Portfolio.cash_balances),
        selectinload(models.Portfolio.transactions),
    )


def create_portfolio(session: Session, payload: schemas.PortfolioCreate) -> models.Portfolio:
    if (
        payload.investor_id is not None
        and session.get(core_models.InvestorProfile, payload.investor_id) is None
    ):
        raise PortfolioNotFoundError("Investor profile not found")
    portfolio = models.Portfolio(
        investor_id=payload.investor_id,
        name=payload.name,
        base_currency=payload.base_currency.upper(),
    )
    session.add(portfolio)
    commit_or_conflict(session, "Portfolio creation conflicted with existing data")
    return get_portfolio(session, portfolio.id)


def list_portfolios(
    session: Session, *, limit: int = 100, offset: int = 0
) -> list[models.Portfolio]:
    statement = _portfolio_statement().order_by(models.Portfolio.id).limit(limit).offset(offset)
    return list(session.scalars(statement).unique())


def get_portfolio(session: Session, portfolio_id: int) -> models.Portfolio:
    statement = _portfolio_statement().where(models.Portfolio.id == portfolio_id)
    portfolio = session.scalar(statement)
    if portfolio is None:
        raise PortfolioNotFoundError("Portfolio not found")
    return portfolio


def _cash_balance(
    session: Session, portfolio: models.Portfolio, currency: str
) -> models.CashBalance:
    normalized = currency.upper()
    balance = next((item for item in portfolio.cash_balances if item.currency == normalized), None)
    if balance is None:
        balance = models.CashBalance(portfolio=portfolio, currency=normalized, balance=ZERO)
        session.add(balance)
    return balance


def _require_funds(balance: models.CashBalance, amount: Decimal) -> None:
    if balance.balance < amount:
        raise PortfolioDomainError(f"Insufficient {balance.currency} cash")


def _record_buy(
    session: Session,
    portfolio: models.Portfolio,
    payload: schemas.TransactionCreate,
    amount: Decimal,
) -> Decimal:
    assert payload.symbol is not None
    assert payload.quantity is not None
    assert payload.unit_price is not None
    if payload.currency.upper() != portfolio.base_currency:
        raise PortfolioDomainError("Position transactions must use the portfolio base currency")
    cash = _cash_balance(session, portfolio, portfolio.base_currency)
    _require_funds(cash, amount)
    symbol = payload.symbol.upper()
    position = next((item for item in portfolio.positions if item.symbol == symbol), None)
    if position is None:
        position = models.PortfolioPosition(
            portfolio=portfolio,
            symbol=symbol,
            asset_name=payload.asset_name or symbol,
            quantity=payload.quantity,
            average_cost=payload.unit_price,
            current_price=payload.unit_price,
            realized_pl=ZERO,
        )
        session.add(position)
    else:
        old_cost = position.quantity * position.average_cost
        new_quantity = _quantity(position.quantity + payload.quantity)
        position.average_cost = _money((old_cost + amount) / new_quantity)
        position.quantity = new_quantity
        if payload.asset_name is not None:
            position.asset_name = payload.asset_name
    cash.balance = _money(cash.balance - amount)
    return ZERO


def _record_sell(
    session: Session,
    portfolio: models.Portfolio,
    payload: schemas.TransactionCreate,
    amount: Decimal,
) -> Decimal:
    assert payload.symbol is not None
    assert payload.quantity is not None
    assert payload.unit_price is not None
    if payload.currency.upper() != portfolio.base_currency:
        raise PortfolioDomainError("Position transactions must use the portfolio base currency")
    symbol = payload.symbol.upper()
    position = next((item for item in portfolio.positions if item.symbol == symbol), None)
    if position is None:
        raise PortfolioDomainError("Position not found")
    if payload.quantity > position.quantity:
        raise PortfolioDomainError("Cannot sell more than the owned quantity")
    realized_pl = _money((payload.unit_price - position.average_cost) * payload.quantity)
    remaining = position.quantity - payload.quantity
    cash = _cash_balance(session, portfolio, portfolio.base_currency)
    cash.balance = _money(cash.balance + amount)
    if remaining == ZERO:
        session.delete(position)
        portfolio.positions.remove(position)
    else:
        position.quantity = remaining
        position.realized_pl = _money(position.realized_pl + realized_pl)
    return realized_pl


def _record_cash_transaction(
    session: Session,
    portfolio: models.Portfolio,
    payload: schemas.TransactionCreate,
    amount: Decimal,
) -> Decimal:
    cash = _cash_balance(session, portfolio, payload.currency)
    if payload.transaction_type in {
        models.TransactionType.deposit,
        models.TransactionType.dividend,
        models.TransactionType.interest,
    }:
        cash.balance = _money(cash.balance + amount)
    else:
        _require_funds(cash, amount)
        cash.balance = _money(cash.balance - amount)
    if (
        payload.transaction_type == models.TransactionType.fee
        and payload.currency.upper() == portfolio.base_currency
    ):
        return -amount
    return ZERO


def record_transaction(
    session: Session, portfolio_id: int, payload: schemas.TransactionCreate
) -> models.PortfolioTransaction:
    portfolio = get_portfolio(session, portfolio_id)
    if payload.transaction_type in {models.TransactionType.buy, models.TransactionType.sell}:
        assert payload.quantity is not None
        assert payload.unit_price is not None
        amount = _money(payload.quantity * payload.unit_price)
    else:
        assert payload.amount is not None
        amount = payload.amount

    try:
        if payload.transaction_type == models.TransactionType.buy:
            realized_pl = _record_buy(session, portfolio, payload, amount)
        elif payload.transaction_type == models.TransactionType.sell:
            realized_pl = _record_sell(session, portfolio, payload, amount)
        else:
            realized_pl = _record_cash_transaction(session, portfolio, payload, amount)

        transaction = models.PortfolioTransaction(
            portfolio_id=portfolio.id,
            transaction_type=payload.transaction_type,
            symbol=payload.symbol.upper() if payload.symbol else None,
            asset_name=payload.asset_name,
            quantity=payload.quantity,
            unit_price=payload.unit_price,
            amount=amount,
            currency=payload.currency.upper(),
            realized_pl=realized_pl,
            note=payload.note,
            occurred_at=_utc_timestamp(payload.occurred_at),
        )
        _mark_mutated(portfolio)
        _verify_accounting_invariants(portfolio)
        session.add(transaction)
        commit_or_conflict(
            session,
            "Portfolio changed concurrently; reload and retry the transaction",
        )
        session.refresh(transaction)
        return transaction
    except (PortfolioDomainError, IntegrityConflictError):
        session.rollback()
        raise


def list_transactions(
    session: Session, portfolio_id: int, *, limit: int = 100, offset: int = 0
) -> list[models.PortfolioTransaction]:
    get_portfolio(session, portfolio_id)
    statement = (
        select(models.PortfolioTransaction)
        .where(models.PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(models.PortfolioTransaction.occurred_at, models.PortfolioTransaction.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def update_position_price(
    session: Session, portfolio_id: int, position_id: int, current_price: Decimal
) -> models.Portfolio:
    portfolio = get_portfolio(session, portfolio_id)
    position = next((item for item in portfolio.positions if item.id == position_id), None)
    if position is None:
        raise PortfolioNotFoundError("Position not found")
    position.current_price = current_price
    _mark_mutated(portfolio)
    _verify_accounting_invariants(portfolio)
    commit_or_conflict(
        session,
        "Portfolio changed concurrently; reload and retry the price update",
    )
    return get_portfolio(session, portfolio_id)


def _allocation_percentages(
    position_values: dict[str, Decimal],
    base_cash: Decimal,
    total_value: Decimal,
) -> dict[str, Decimal]:
    if not total_value:
        return {}
    components = sorted(position_values.items())
    if base_cash:
        components.append(("CASH", base_cash))
    allocations: dict[str, Decimal] = {}
    allocated = ZERO
    for name, value in components[:-1]:
        percentage = _money(value / total_value * PERCENT)
        allocations[name] = percentage
        allocated += percentage
    last_name, _ = components[-1]
    allocations[last_name] = _money(PERCENT - allocated)
    return allocations


def portfolio_summary(portfolio: models.Portfolio) -> schemas.PortfolioSummary:
    position_values = {
        position.symbol: _money(position.quantity * position.current_price)
        for position in portfolio.positions
    }
    position_value = _money(sum(position_values.values(), ZERO))
    total_cost_basis = _money(
        sum(
            (position.quantity * position.average_cost for position in portfolio.positions),
            ZERO,
        )
    )
    realized_pl = _money(
        sum((transaction.realized_pl for transaction in portfolio.transactions), ZERO)
    )
    base_cash = next(
        (
            balance.balance
            for balance in portfolio.cash_balances
            if balance.currency == portfolio.base_currency
        ),
        ZERO,
    )
    total_value = _money(position_value + base_cash)
    allocations = _allocation_percentages(position_values, base_cash, total_value)
    cash_balances = {
        balance.currency: balance.balance
        for balance in sorted(portfolio.cash_balances, key=lambda item: item.currency)
    }
    return schemas.PortfolioSummary(
        portfolio_id=portfolio.id,
        valuation_currency=portfolio.base_currency,
        total_value=total_value,
        position_value=position_value,
        base_cash_balance=base_cash,
        total_cost_basis=total_cost_basis,
        realized_pl=realized_pl,
        unrealized_pl=_money(position_value - total_cost_basis),
        allocations=allocations,
        cash_balances=cash_balances,
        unconverted_cash_currencies=[
            currency for currency in cash_balances if currency != portfolio.base_currency
        ],
    )


def portfolio_to_read(portfolio: models.Portfolio) -> schemas.PortfolioRead:
    summary = portfolio_summary(portfolio)
    positions = [
        schemas.PositionRead(
            id=position.id,
            symbol=position.symbol,
            asset_name=position.asset_name,
            quantity=position.quantity,
            average_cost=position.average_cost,
            current_price=position.current_price,
            market_value=_money(position.quantity * position.current_price),
            cost_basis=_money(position.quantity * position.average_cost),
            realized_pl=position.realized_pl,
            unrealized_pl=_money(
                position.quantity * (position.current_price - position.average_cost)
            ),
            allocation_percentage=summary.allocations.get(position.symbol, ZERO),
        )
        for position in sorted(portfolio.positions, key=lambda item: item.symbol)
    ]
    return schemas.PortfolioRead(
        id=portfolio.id,
        investor_id=portfolio.investor_id,
        name=portfolio.name,
        base_currency=portfolio.base_currency,
        lock_version=portfolio.lock_version,
        created_at=portfolio.created_at,
        positions=positions,
        cash_balances=[
            schemas.CashBalanceRead.model_validate(balance)
            for balance in sorted(portfolio.cash_balances, key=lambda item: item.currency)
        ],
    )


def create_snapshot(session: Session, portfolio_id: int) -> models.PortfolioSnapshot:
    portfolio = get_portfolio(session, portfolio_id)
    summary = portfolio_summary(portfolio)
    snapshot = models.PortfolioSnapshot(
        portfolio_id=portfolio.id,
        captured_at=datetime.now(UTC),
        total_value=summary.total_value,
        position_value=summary.position_value,
        base_cash_balance=summary.base_cash_balance,
        total_cost_basis=summary.total_cost_basis,
        realized_pl=summary.realized_pl,
        unrealized_pl=summary.unrealized_pl,
        allocations_json=json.dumps(
            {key: str(value) for key, value in summary.allocations.items()}, sort_keys=True
        ),
        cash_balances_json=json.dumps(
            {key: str(value) for key, value in summary.cash_balances.items()}, sort_keys=True
        ),
    )
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def list_snapshots(
    session: Session, portfolio_id: int, *, limit: int = 100, offset: int = 0
) -> list[models.PortfolioSnapshot]:
    get_portfolio(session, portfolio_id)
    statement = (
        select(models.PortfolioSnapshot)
        .where(models.PortfolioSnapshot.portfolio_id == portfolio_id)
        .order_by(models.PortfolioSnapshot.captured_at, models.PortfolioSnapshot.id)
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement))


def snapshot_to_read(snapshot: models.PortfolioSnapshot) -> schemas.SnapshotRead:
    return schemas.SnapshotRead(
        id=snapshot.id,
        portfolio_id=snapshot.portfolio_id,
        captured_at=snapshot.captured_at,
        total_value=snapshot.total_value,
        position_value=snapshot.position_value,
        base_cash_balance=snapshot.base_cash_balance,
        total_cost_basis=snapshot.total_cost_basis,
        realized_pl=snapshot.realized_pl,
        unrealized_pl=snapshot.unrealized_pl,
        allocations={
            key: Decimal(value) for key, value in json.loads(snapshot.allocations_json).items()
        },
        cash_balances={
            key: Decimal(value) for key, value in json.loads(snapshot.cash_balances_json).items()
        },
        created_at=snapshot.created_at,
    )
