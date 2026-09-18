"""Books, allocation, netting, internal crosses, PnL, reserves, status."""

from __future__ import annotations

from decimal import Decimal

import pytest

from zipline_engine.accounting.allocation import (
    EqualWeightPolicy,
    ManualWeightPolicy,
    SleeveInfo,
    check_max_strategy_allocation,
    deployable_capital,
    distribute,
)
from zipline_engine.accounting.books import Book, InsufficientCashError, InsufficientPositionError
from zipline_engine.accounting.netting import (
    RiskLimits,
    apply_risk_limits,
    cross_internally,
    plan,
    split_pro_rata,
)
from zipline_engine.accounting.status import evaluate_status
from zipline_engine.db.enums import Side, StrategyStatus

D = Decimal

LIMITS = RiskLimits(
    max_single_asset_pct=D(20),
    max_order_pct_of_treasury=D(10),
    max_daily_turnover_pct=D(50),
    min_trade_notional_pct=D("0.25"),
    cash_reserve_pct=D(10),
    sleeve_min_delta_pct=D(0),
)


# ------------------------------------------------------------------ books / PnL


def test_average_cost_realized_and_unrealized(book: Book) -> None:
    book.apply_fill("AAPL", Side.BUY, D("2"), D("100"))
    book.apply_fill("AAPL", Side.BUY, D("2"), D("120"))
    pos = book.positions["AAPL"]
    assert pos.quantity == D(4) and pos.avg_cost == D(110)
    assert book.cash == D(1000) - D(440)
    val = book.mark({"AAPL": D("130")})
    assert val.unrealized_pnl == D(80)
    fill = book.apply_fill("AAPL", Side.SELL, D("1"), D("130"))
    assert fill.realized_pnl == D(20)
    assert book.realized_pnl == D(20)
    val = book.mark({"AAPL": D("130")})
    assert val.unrealized_pnl == D(60)
    assert val.nav == D(1000) + D(80)  # 20 realized + 60 unrealized


def test_book_rejects_overspend_and_oversell(book: Book) -> None:
    with pytest.raises(InsufficientCashError):
        book.apply_fill("AAPL", Side.BUY, D("100"), D("100"))
    with pytest.raises(InsufficientPositionError):
        book.apply_fill("AAPL", Side.SELL, D("1"), D("100"))


def test_twr_ignores_contributions(book: Book) -> None:
    book.apply_fill("SPY", Side.BUY, D("1"), D("500"))
    book.mark({"SPY": D("500")})
    book.add_capital(D("1000"))  # deposit, not profit
    val = book.mark({"SPY": D("500")})
    assert val.twr_index == D(1)
    assert val.nav == D(2000)
    val = book.mark({"SPY": D("550")})  # +50 on a 2000 base = +2.5%
    assert val.twr_index.quantize(D("0.0001")) == D("1.0250")


def test_drawdown_from_twr_peak(book: Book) -> None:
    book.apply_fill("SPY", Side.BUY, D("2"), D("500"))
    book.mark({"SPY": D("600")})  # peak
    val = book.mark({"SPY": D("540")})
    assert val.drawdown_pct < 0
    assert book.max_drawdown_pct == val.drawdown_pct
    assert val.drawdown_pct.quantize(D("0.01")) == D("-10.00")  # 1200 -> 1080 on a 1200 NAV: -10%


# ------------------------------------------------------------------ allocation


def test_deployable_capital_and_reserve() -> None:
    assert deployable_capital(D(5000), D(10)) == D("4500")
    assert deployable_capital(D(0), D(10)) == 0
    assert deployable_capital(D("57.31"), D(10)) == D("51.579")


def test_distribute_is_exact() -> None:
    parts = distribute(D("1000"), {"A": D(1), "B": D(1), "C": D(1)})
    assert sum(parts.values()) == D("1000")
    assert len(parts) == 3


def test_policies() -> None:
    sleeves = [
        SleeveInfo("A", True, D(10)),
        SleeveInfo("B", True, D(30)),
        SleeveInfo("C", False, D(60)),
    ]
    eq = EqualWeightPolicy().target_weights(sleeves)
    assert eq == {"A": D("0.5"), "B": D("0.5")}
    manual = ManualWeightPolicy().target_weights(sleeves)
    assert manual["A"] == D("0.25") and manual["B"] == D("0.75")


def test_max_strategy_allocation_check() -> None:
    assert check_max_strategy_allocation({"A": D("0.1")}, D(20), D(10)) == []
    assert check_max_strategy_allocation({"A": D("0.5")}, D(20), D(10))


# ------------------------------------------------------------------ netting


def _books(prices: dict[str, Decimal]) -> dict[str, Book]:
    books = {}
    for code in ("TREND", "MOMENTUM", "MEANREV"):
        b = Book(code)
        b.add_capital(D(1000))
        books[code] = b
    books["MEANREV"].apply_fill("NVDA", Side.BUY, D("2"), prices["NVDA"])  # holds 300 of NVDA
    for b in books.values():
        b.mark(prices)
    return books


def test_netting_example_from_spec(prices: dict[str, Decimal]) -> None:
    """TREND +3%, MOMENTUM +2%, MEANREV -1% of treasury in NVDA -> cross 1%, net +4% external."""
    books = _books(prices)
    nav = {c: b.nav(prices) for c, b in books.items()}
    treasury_nav = sum(nav.values(), D(0))  # 3000
    # express treasury-relative targets as sleeve weights
    targets = {
        "TREND": {"NVDA": D("0.03") * treasury_nav / nav["TREND"]},
        "MOMENTUM": {"NVDA": D("0.02") * treasury_nav / nav["MOMENTUM"]},
        "MEANREV": {
            "NVDA": (D(300) - D("0.01") * treasury_nav) / nav["MEANREV"]
        },  # sell 30 of its 300
    }
    result = plan(
        targets,
        books,
        prices,
        hold_only=set(),
        treasury_nav=treasury_nav,
        treasury_cash=D(2700),
        treasury_positions={"NVDA": D(2)},
        limits=LIMITS,
    )
    crossed = sum((c.notional for c in result.crosses), D(0))
    assert crossed.quantize(D("0.01")) == D("30.00")  # 1% of 3000 crossed internally
    assert len(result.net_orders) == 1
    order = result.net_orders[0]
    assert order.side == Side.BUY and order.symbol == "NVDA"
    assert order.notional.quantize(D("0.01")) == D("120.00")  # 4% of 3000 goes onchain
    assert {p.code for p in order.participants} == {"TREND", "MOMENTUM"}
    assert all(c.seller == "MEANREV" for c in result.crosses)


def test_cross_matching_conserves_quantity() -> None:
    from zipline_engine.accounting.netting import SleeveDelta

    deltas = [
        SleeveDelta("A", "X", D("5"), D(10)),
        SleeveDelta("B", "X", D("3"), D(10)),
        SleeveDelta("C", "X", D("-6"), D(10)),
    ]
    crosses, net = cross_internally(deltas)
    assert sum((c.quantity for c in crosses), D(0)) == D(6)
    assert len(net) == 1 and net[0].side == Side.BUY and net[0].quantity == D(2)
    assert sum((p.quantity for p in net[0].participants), D(0)) == D(2)


def test_split_pro_rata_exact() -> None:
    parts = split_pro_rata(D("1"), [("A", D(1)), ("B", D(1)), ("C", D(1))])
    assert sum((p.quantity for p in parts), D(0)) == D("1")


def test_risk_limits_single_asset_order_size_turnover_reserve() -> None:
    from zipline_engine.accounting.netting import NetOrder, Participation

    nav, cash = D(10000), D(10000)
    orders = [
        NetOrder(
            "AAPL", Side.BUY, D("15"), D(200), [Participation("A", D("15"))]
        ),  # 3000 = 30% of NAV
        NetOrder("MSFT", Side.BUY, D("10"), D(400), [Participation("A", D("10"))]),  # 4000
    ]
    out, notes = apply_risk_limits(
        orders,
        treasury_nav=nav,
        treasury_cash=cash,
        treasury_positions={},
        prices={},
        limits=LIMITS,
    )
    by = {o.symbol: o for o in out}
    assert by["AAPL"].notional <= nav * D("0.10") + D(
        "0.01"
    )  # MAX_ORDER 10% binds before MAX_SINGLE 20%
    assert by["MSFT"].notional <= nav * D("0.10") + D("0.01")
    assert any("MAX_SINGLE_ASSET_PCT" in n for n in notes) and any(
        "MAX_ORDER_PCT_OF_TREASURY" in n for n in notes
    )
    # turnover: 4 orders of 1000 with 50% cap and 1500 already traded today -> scaled
    orders = [
        NetOrder(s, Side.BUY, D("5"), D(200), [Participation("A", D("5"))])
        for s in ("A", "B", "C", "D")
    ]
    out, notes = apply_risk_limits(
        orders,
        treasury_nav=nav,
        treasury_cash=cash,
        treasury_positions={},
        prices={},
        limits=LIMITS,
        turnover_today=D(1500),
    )
    assert sum((o.notional for o in out), D(0)) <= D(3500) + D("0.01")
    # reserve: only 900 spendable above the 10% reserve
    orders = [NetOrder("A", Side.BUY, D("4"), D(200), [Participation("A", D("4"))])]
    out, notes = apply_risk_limits(
        orders,
        treasury_nav=nav,
        treasury_cash=D(1700),
        treasury_positions={},
        prices={},
        limits=LIMITS,
    )
    assert out[0].notional <= D(700) + D("0.01")
    assert any("CASH_RESERVE_PCT" in n for n in notes)


def test_min_trade_filter_drops_dust() -> None:
    from zipline_engine.accounting.netting import NetOrder, Participation

    orders = [
        NetOrder("A", Side.BUY, D("0.01"), D(100), [Participation("A", D("0.01"))])
    ]  # $1 on $10k
    out, notes = apply_risk_limits(
        orders,
        treasury_nav=D(10000),
        treasury_cash=D(10000),
        treasury_positions={},
        prices={},
        limits=LIMITS,
    )
    assert out == [] and any("MIN_TRADE_NOTIONAL_PCT" in n for n in notes)


def test_hold_only_asset_is_carried_not_sold(prices: dict[str, Decimal]) -> None:
    books = _books(prices)
    result = plan(
        {"MEANREV": {}},
        {"MEANREV": books["MEANREV"]},
        prices,
        hold_only={"NVDA"},
        treasury_nav=D(1000),
        treasury_cash=D(700),
        treasury_positions={"NVDA": D(2)},
        limits=LIMITS,
    )
    assert result.net_orders == [] and result.sleeve_deltas == []


def test_removed_asset_is_liquidated(prices: dict[str, Decimal]) -> None:
    books = _books(prices)
    result = plan(
        {"MEANREV": {}},
        {"MEANREV": books["MEANREV"]},
        prices,
        hold_only=set(),
        treasury_nav=D(1000),
        treasury_cash=D(700),
        treasury_positions={"NVDA": D(2)},
        limits=LIMITS,
    )
    assert len(result.net_orders) == 1 and result.net_orders[0].side == Side.SELL
    # liquidation is still subject to the per-order cap (10% of NAV = 100 = 0.667 NVDA); it completes over cycles
    assert D(0) < result.net_orders[0].quantity <= D(2)
    assert any("MAX_ORDER_PCT_OF_TREASURY" in n for n in result.risk_notes)


# ------------------------------------------------------------------ status


def test_status_rules_are_percentage_based() -> None:
    kw = dict(
        enabled=True, current_status="ACTIVE", watch_drawdown_pct=D(10), disable_drawdown_pct=D(25)
    )
    assert evaluate_status(drawdown_pct=D("-3"), **kw)[0] == StrategyStatus.ACTIVE
    assert evaluate_status(drawdown_pct=D("-12"), **kw)[0] == StrategyStatus.WATCH
    assert evaluate_status(drawdown_pct=D("-30"), **kw)[0] == StrategyStatus.DISABLED
    assert (
        evaluate_status(
            enabled=False,
            current_status="ACTIVE",
            drawdown_pct=D(0),
            watch_drawdown_pct=D(10),
            disable_drawdown_pct=D(25),
        )[0]
        == StrategyStatus.DISABLED
    )
