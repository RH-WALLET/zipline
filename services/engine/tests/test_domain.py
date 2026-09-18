"""Multiplier semantics, eligibility, calendar, reconciliation, funding math, pricing fallbacks."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from zipline_engine.accounting.books import Book
from zipline_engine.accounting.repository import BookRepository
from zipline_engine.config import Settings
from zipline_engine.core.calendar import (
    is_session,
    last_completed_session,
    next_cycle_time,
    session_index,
    sessions_between,
)
from zipline_engine.core.multiplier import (
    multiplier_from_ui,
    parse_api_multiplier,
    position_value,
    shares_from_tokens,
    token_price,
    tokens_for_notional,
)
from zipline_engine.db.enums import ReconciliationStatus, Side
from zipline_engine.reconciliation.service import reconcile
from zipline_engine.robinhood.client import RHPrice
from zipline_engine.robinhood.universe import EligibilityInput, evaluate_eligibility
from zipline_engine.treasury.backends import TreasuryBalances
from zipline_engine.treasury.funding import CapitalAllocator

D = Decimal


# ------------------------------------------------------------------ multiplier


def test_multiplier_semantics_split_invariance() -> None:
    # 1 raw token, multiplier 1, share price 400 -> $400
    assert token_price(D(400), D(1)) == D(400)
    # 4:1 split: multiplier 4, share price 100 -> the same raw token is still worth $400
    assert token_price(D(100), D(4)) == D(400)
    assert shares_from_tokens(D("2.5"), D(4)) == D(10)
    assert position_value(D("2.5"), D(100), D(4)) == D(1000)
    assert tokens_for_notional(D(1000), D(100), D(4)) == D("2.5")


def test_multiplier_parsing() -> None:
    assert multiplier_from_ui(10**18) == D(1)
    assert multiplier_from_ui(4 * 10**18) == D(4)
    assert parse_api_multiplier("1.001148322800714293") == D("1.001148322800714293")
    assert parse_api_multiplier(None) == D(1)
    with pytest.raises(ValueError):
        parse_api_multiplier("0")


def test_dividend_multiplier_increases_token_value_not_pnl_on_split() -> None:
    book = Book("X")
    book.add_capital(D(1000))
    book.apply_fill("CRWD", Side.BUY, D(1), token_price(D(400), D(1)))  # buys 1 raw token at $400
    val_before = book.mark({"CRWD": token_price(D(400), D(1))})
    val_after = book.mark({"CRWD": token_price(D(100), D(4))})  # 4:1 split
    assert val_before.nav == val_after.nav == D(1000)
    assert val_after.unrealized_pnl == 0


# ------------------------------------------------------------------ eligibility


def price(
    halted: bool = False, bid: str | None = "100", ask: str | None = "100.1", volume: str = "1000"
) -> RHPrice:
    return RHPrice(
        tokenSymbol="X",
        bid=bid,
        ask=ask,
        dailyTradingVolume=volume,
        isTradingHalt=halted,
        generatedAt=datetime.now(UTC),
    )


def base_input(**kw):  # type: ignore[no-untyped-def]
    args = dict(
        symbol="X",
        in_allowlist=True,
        seen_in_api=True,
        status="ASSET_STATUS_ACTIVE",
        tradable=True,
        has_deployment=True,
        contract_verified=True,
        decimals_ok=True,
        price=price(),
        daily_volume=D(1000),
    )
    args.update(kw)
    return EligibilityInput(**args)


def test_eligibility_all_gates() -> None:
    assert evaluate_eligibility(base_input()).eligible
    halted = evaluate_eligibility(base_input(price=price(halted=True)))
    assert not halted.eligible and halted.hold_only and "halted" in halted.reasons
    inactive = evaluate_eligibility(base_input(status="ASSET_STATUS_INACTIVE"))
    assert not inactive.eligible and not inactive.hold_only
    missing = evaluate_eligibility(base_input(seen_in_api=False, price=None))
    assert missing.hold_only  # temporarily unavailable -> carry, do not trade
    assert not evaluate_eligibility(base_input(has_deployment=False)).eligible
    assert not evaluate_eligibility(base_input(contract_verified=False)).eligible
    assert not evaluate_eligibility(base_input(decimals_ok=False)).eligible
    assert not evaluate_eligibility(
        base_input(price=price(bid="100.5", ask="100"))
    ).eligible  # crossed book
    assert not evaluate_eligibility(base_input(daily_volume=D(0))).eligible
    assert not evaluate_eligibility(base_input(route_ok=False)).eligible
    impact = evaluate_eligibility(base_input(probe_impact_bps=D(500), max_impact_bps=150))
    assert not impact.eligible and any(r.startswith("price_impact") for r in impact.reasons)
    assert not evaluate_eligibility(base_input(tradable=False)).eligible
    # unverified (no RPC) is not a failure
    assert evaluate_eligibility(base_input(contract_verified=None, decimals_ok=None)).eligible


def test_rhprice_validity() -> None:
    assert price().valid and price().mid == D("100.05")
    assert not price(bid=None).valid
    assert not price(bid="0", ask="1").valid


# ------------------------------------------------------------------ calendar


def test_calendar_helpers() -> None:
    assert is_session(date(2026, 9, 17)) and not is_session(date(2026, 9, 19))  # Saturday
    assert not is_session(date(2026, 7, 3))  # Independence Day observed
    assert sessions_between(date(2026, 9, 14), date(2026, 9, 18)) == [
        date(2026, 9, 14 + i) for i in range(5)
    ]
    assert last_completed_session(datetime(2026, 9, 18, 13, 0, tzinfo=UTC)) == date(
        2026, 9, 17
    )  # 09:00 ET, market not closed yet
    assert last_completed_session(datetime(2026, 9, 18, 20, 30, tzinfo=UTC)) == date(
        2026, 9, 18
    )  # after 16:00 ET
    assert last_completed_session(datetime(2026, 9, 20, 12, 0, tzinfo=UTC)) == date(
        2026, 9, 18
    )  # Sunday
    nxt = next_cycle_time("16:20", datetime(2026, 9, 18, 13, 0, tzinfo=UTC))
    assert nxt == datetime(2026, 9, 18, 20, 20, tzinfo=UTC)
    nxt = next_cycle_time("16:20", datetime(2026, 9, 18, 21, 0, tzinfo=UTC))
    assert nxt.date() == date(2026, 9, 21)  # next Monday
    assert session_index(date(2026, 9, 17)) == session_index(date(2026, 9, 16)) + 1


# ------------------------------------------------------------------ reconciliation


def _balances(cash: str, positions: dict[str, str]) -> TreasuryBalances:
    return TreasuryBalances(
        "simulated",
        "test",
        None,
        D(cash),
        {k: D(v) for k, v in positions.items()},
        D("0.05"),
        datetime.now(UTC),
    )


def test_reconciliation_ok_within_rounding_tolerance() -> None:
    a, b = Book("A"), Book("B")
    a.add_capital(D(500))
    b.add_capital(D(500))
    a.apply_fill("NVDA", Side.BUY, D("1.000000000000000001"), D(100))
    b.apply_fill("NVDA", Side.BUY, D("1"), D(100))
    treasury = _balances("900", {"NVDA": "2.000000000000000000"})  # 1e-18 token rounding difference
    res = reconcile(
        {"A": a, "B": b},
        treasury,
        {"NVDA": D(100)},
        nav=D(1100),
        tolerance_bps=10,
        reserve_target=D(110),
    )
    assert res.status == ReconciliationStatus.OK
    assert res.buffer_cash.quantize(D("0.0001")) == (
        D(900) - BookRepository.sum_cash({"A": a, "B": b})
    ).quantize(D("0.0001"))


def test_reconciliation_fails_on_position_break_and_phantom_cash() -> None:
    a = Book("A")
    a.add_capital(D(1000))
    a.apply_fill("NVDA", Side.BUY, D("2"), D(100))
    treasury = _balances("800", {"NVDA": "1.5"})  # treasury holds less than the books claim
    res = reconcile(
        {"A": a}, treasury, {"NVDA": D(100)}, nav=D(950), tolerance_bps=10, reserve_target=D(95)
    )
    assert res.status == ReconciliationStatus.FAILED and res.position_breaks[0]["symbol"] == "NVDA"
    phantom = _balances("700", {"NVDA": "2"})  # books hold 800 cash but the treasury only has 700
    res = reconcile(
        {"A": a}, phantom, {"NVDA": D(100)}, nav=D(900), tolerance_bps=10, reserve_target=D(90)
    )
    assert res.status == ReconciliationStatus.FAILED and res.cash_break < 0


def test_reconciliation_unpriced_break_counts() -> None:
    a = Book("A")
    a.add_capital(D(1000))
    a.apply_fill("ZZZ", Side.BUY, D("1"), D(10))
    res = reconcile(
        {"A": a}, _balances("990", {}), {}, nav=D(1000), tolerance_bps=10, reserve_target=D(100)
    )
    assert res.status == ReconciliationStatus.FAILED


# ------------------------------------------------------------------ funding / withdrawals


def test_capital_allocation_holds_back_reserve_and_splits_by_weight() -> None:
    settings = Settings(cash_reserve_pct=D(10), _env_file=None)  # type: ignore[call-arg]
    allocator = CapitalAllocator(settings)
    from types import SimpleNamespace

    strategies = {c: SimpleNamespace(status="ACTIVE", enabled=True) for c in ("A", "B")}
    strategies["C"] = SimpleNamespace(status="DISABLED", enabled=False)
    books = {c: Book(c) for c in ("A", "B", "C")}
    out = allocator.allocate(D(1000), strategies, books, {"A": D(10), "B": D(30), "C": D(60)})  # type: ignore[arg-type]
    assert out.to_reserve == D(100)
    assert out.to_sleeves == {
        "A": D("225"),
        "B": D("675"),
    }  # 900 split 1:3 over ACTIVE sleeves only
    assert (
        books["C"].cash == 0
        and books["A"].cash == D(225)
        and books["A"].allocated_capital == D(225)
    )


def test_withdrawal_deallocation_prefers_buffer_then_sleeve_cash() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    allocator = CapitalAllocator(settings)
    books = {"A": Book("A"), "B": Book("B")}
    books["A"].add_capital(D(300))
    books["B"].add_capital(D(100))
    taken = allocator.deallocate(
        D(150), books, buffer_cash=D(100)
    )  # 100 from buffer, 50 pro-rata from sleeves
    assert sum(taken.values()) == D(50)
    assert taken["A"] == D("37.5") and taken["B"] == D("12.5")
    assert books["A"].allocated_capital == D("262.5")  # a withdrawal is not a loss
    with pytest.raises(ValueError):
        allocator.deallocate(D(10000), books, buffer_cash=D(0))
