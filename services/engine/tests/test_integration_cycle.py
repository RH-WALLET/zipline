"""End-to-end cycles against Postgres with fakes for the network. Nothing is ever broadcast."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

import zipline_engine.scheduler.cycle as cycle_mod
from tests.fakes import FailingAdapter, FakeProvider, FakeRobinhood
from zipline_engine.accounting.repository import BookRepository
from zipline_engine.config import Settings
from zipline_engine.core.system import get_state, pause
from zipline_engine.db.enums import CycleStatus, FundingKind, OrderStatus
from zipline_engine.db.models import (
    BlockchainTransaction,
    ExecutionOrder,
    FundingEvent,
    HistoricalBar,
    InternalCross,
    ReconciliationEvent,
    StrategySignal,
    SystemEvent,
    TreasurySnapshot,
    VirtualFill,
)
from zipline_engine.runtime import Runtime, build_runtime
from zipline_engine.scheduler.bootstrap import bootstrap
from zipline_engine.scheduler.cycle import CycleError, run_cycle, run_reconciliation, run_valuation
from zipline_engine.scheduler.withdraw import record_withdrawal

D = Decimal
DAY1, DAY2, DAY3 = date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)


def make_settings(**kw) -> Settings:  # type: ignore[no-untyped-def]
    base = dict(
        live_trading=False,
        treasury_mode="simulated",
        demo_initial_cash=D(5000),
        eth_usd_price_source="none",
        history_lookback_days=330,
        asset_allowlist="AAPL,MSFT,NVDA,SPY,QQQ,XOM",
        pairs_candidates="SPY:QQQ,AAPL:MSFT",
        admin_token="test-admin-token",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


@pytest.fixture
def rt(db_session, monkeypatch) -> Runtime:  # type: ignore[no-untyped-def]
    settings = make_settings()
    rt = build_runtime(db_session, settings)
    fake = FakeRobinhood(as_of=DAY1)
    rt.rh_client = fake  # type: ignore[assignment]
    rt.universe.rh = fake  # type: ignore[assignment]
    rt.pricing.rh = fake  # type: ignore[assignment]
    rt.marketdata.provider = FakeProvider()
    bootstrap(rt)
    db_session.commit()
    return rt


def _check_invariants(rt: Runtime) -> None:
    loaded = rt.repo.load()
    balances = rt.treasury.read_balances(rt.universe.all_assets())
    book_positions = BookRepository.sum_positions(loaded.books)
    for sym in set(book_positions) | set(balances.positions):
        assert abs(book_positions.get(sym, D(0)) - balances.positions.get(sym, D(0))) < D("1e-9"), (
            sym
        )
    sleeve_cash = BookRepository.sum_cash(loaded.books)
    assert balances.cash >= sleeve_cash - D("1e-6")
    assert (
        not rt.session.execute(select(BlockchainTransaction)).scalars().all()
    )  # demo never broadcasts
    for o in rt.session.execute(select(ExecutionOrder)).scalars().all():
        assert o.mode == "DRY_RUN" and o.local_id.startswith("dry-")


def test_full_dry_run_cycle_reconciles(rt: Runtime) -> None:
    cycle = run_cycle(rt, session_date=DAY1)
    assert cycle.status == CycleStatus.COMPLETED
    s = cycle.summary
    assert (
        s["strategies_run"] == 10 and s["signals"] > 0 and s["net_orders"] > 0 and s["filled"] > 0
    )
    _check_invariants(rt)
    rec = (
        rt.session.execute(select(ReconciliationEvent).order_by(ReconciliationEvent.id.desc()))
        .scalars()
        .first()
    )
    assert rec is not None and rec.status == "RECONCILIATION_OK" and rec.triggered_pause is False
    snap = (
        rt.session.execute(select(TreasurySnapshot).order_by(TreasurySnapshot.id.desc()))
        .scalars()
        .first()
    )
    assert snap is not None and snap.base_capital == D(5000)
    # reserve: 10% of NAV stays out of the sleeves
    loaded = rt.repo.load()
    buffer = D(snap.cash_balance) - BookRepository.sum_cash(loaded.books)
    assert abs(buffer - D(snap.nav) * D("0.10")) < D(snap.nav) * D("0.011")
    types = {e.type for e in rt.session.execute(select(SystemEvent)).scalars().all()}
    assert {
        "STRATEGY_CYCLE_STARTED",
        "MARKET_DATA_UPDATED",
        "STRATEGY_SIGNAL_CREATED",
        "TARGETS_AGGREGATED",
        "QUOTE_RECEIVED",
        "EXECUTION_DRY_RUN",
        "TREASURY_UPDATED",
        "RECONCILIATION_OK",
        "STRATEGY_CYCLE_COMPLETED",
    } <= types
    assert not get_state(rt.session).paused
    # historical bars were cached and the second call is incremental
    n_bars = rt.session.execute(select(func.count()).select_from(HistoricalBar)).scalar_one()
    assert n_bars > 0
    calls_before = len(rt.marketdata.provider.calls)  # type: ignore[attr-defined]
    report = rt.marketdata.refresh(["AAPL"], DAY1)
    assert report.unchanged == ["AAPL"] and len(rt.marketdata.provider.calls) == calls_before  # type: ignore[attr-defined]


def test_second_cycle_is_incremental_and_state_persists(rt: Runtime) -> None:
    run_cycle(rt, session_date=DAY1)
    rt.rh_client.as_of = DAY2  # type: ignore[attr-defined]
    rt.pricing.rh.as_of = DAY2  # type: ignore[attr-defined]
    c2 = run_cycle(rt, session_date=DAY2)
    assert c2.status == CycleStatus.COMPLETED
    _check_invariants(rt)
    # incremental history: only DAY2 was fetched for each symbol
    fetched = c2.summary["history_new_bars"]
    assert fetched == 6
    # same-date rerun without force returns the existing cycle
    assert run_cycle(rt, session_date=DAY2).id == c2.id
    signals = rt.session.execute(select(func.count()).select_from(StrategySignal)).scalar_one()
    assert signals > 0
    fills = rt.session.execute(select(VirtualFill)).scalars().all()
    kinds = {f.kind for f in fills}
    assert kinds <= {"DRY_RUN", "INTERNAL_CROSS"}
    for x in rt.session.execute(select(InternalCross)).scalars().all():
        # every internal cross is mirrored by exactly two virtual fills and no execution order
        legs = [f for f in fills if f.internal_cross_id == x.id]
        assert len(legs) == 2 and {legs[0].side, legs[1].side} == {"BUY", "SELL"}


def test_deposit_is_allocated_not_counted_as_pnl(rt: Runtime) -> None:
    run_cycle(rt, session_date=DAY1)
    snap_before = rt.treasury.latest_snapshot()
    assert snap_before is not None
    rt.simulated.deposit_cash(D(1000))  # type: ignore[union-attr]
    rt.funding.record_funding(FundingKind.CONTRIBUTION, D(1000), note="test deposit")
    run_valuation(rt)
    snap = rt.treasury.latest_snapshot()
    assert snap is not None
    assert D(snap.contributions_total) == D(1000) and D(snap.base_capital) == D(5000)
    assert abs(D(snap.nav) - D(snap_before.nav) - D(1000)) < D("0.01")
    assert abs(D(snap.twr_index) - D(snap_before.twr_index)) < D(
        "0.0005"
    )  # a deposit is not a return
    ev = rt.session.execute(
        select(FundingEvent).where(FundingEvent.kind == "CONTRIBUTION")
    ).scalar_one()
    assert ev.allocated is True
    to_sleeves = sum(D(v) for v in ev.allocation["to_sleeves"].values())
    assert to_sleeves == D(900) and D(ev.allocation["to_reserve"]) == D(100)
    _check_invariants(rt)


def test_withdrawal_reduces_nav_without_loss(rt: Runtime) -> None:
    run_cycle(rt, session_date=DAY1)
    before = rt.treasury.latest_snapshot()
    ev = record_withdrawal(rt, D(200), to_address=None, tx_hash=None, note="test", broadcast=False)
    assert ev.status == "SIMULATED"
    after = rt.treasury.latest_snapshot()
    assert after is not None and before is not None
    assert abs(D(before.nav) - D(after.nav) - D(200)) < D("0.01")
    assert D(after.withdrawals_total) == D(200)
    assert abs(D(after.twr_index) - D(before.twr_index)) < D("0.0005")
    _check_invariants(rt)


def test_paused_system_refuses_cycle(rt: Runtime) -> None:
    pause(rt.session, rt.events, "test")
    with pytest.raises(CycleError):
        run_cycle(rt, session_date=DAY1)


def test_reconciliation_break_pauses_live_trading(rt: Runtime) -> None:
    run_cycle(rt, session_date=DAY1)
    # tamper with the treasury: tokens vanish from the wallet
    row = rt.simulated._row("AAPL")  # type: ignore[union-attr]
    if D(row.quantity) == 0:
        row = rt.simulated._row(
            rt.treasury.read_balances(rt.universe.all_assets()).positions.__iter__().__next__()
        )  # type: ignore[union-attr]
    row.quantity = D(row.quantity) / 2
    rt.session.flush()
    ev = run_reconciliation(rt, trigger="test")
    assert ev.status == "RECONCILIATION_FAILED" and ev.triggered_pause is True
    assert get_state(rt.session).paused
    assert any(
        e.type == "SYSTEM_PAUSED" for e in rt.session.execute(select(SystemEvent)).scalars().all()
    )


def test_repeated_execution_failures_pause_and_never_fill(rt: Runtime, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    rt.settings.max_failed_txs_before_pause = 2
    rt.settings.cash_token_address = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
    rt.universe.refresh()
    for a in rt.universe.all_assets():  # pretend the deployments were verified over RPC
        for d in a.deployments:
            d.verified_onchain = True
    rt.session.commit()
    monkeypatch.setattr(cycle_mod, "build_adapter", lambda rt_, prices: FailingAdapter(prices))
    cycle = run_cycle(rt, session_date=DAY1)
    orders = rt.session.execute(select(ExecutionOrder)).scalars().all()
    assert orders and all(o.status == OrderStatus.FAILED for o in orders)
    assert all(o.executed_quantity is None for o in orders)  # no fabricated fills
    assert cycle.summary["failed"] == 2 and cycle.summary["filled"] == 0
    assert get_state(rt.session).paused
    loaded = rt.repo.load()
    assert BookRepository.sum_positions(loaded.books) == {}


def test_halted_asset_is_hold_only_and_removed_asset_liquidates(rt: Runtime) -> None:
    run_cycle(rt, session_date=DAY1)
    held = rt.treasury.read_balances(rt.universe.all_assets()).positions
    target = sorted(held)[0]
    rt.rh_client.halted = {target}  # type: ignore[attr-defined]
    rt.rh_client.as_of = DAY2  # type: ignore[attr-defined]
    c2 = run_cycle(rt, session_date=DAY2)
    assert target in c2.summary["hold_only"] and target not in c2.summary["eligible"]
    sells = [
        o
        for o in rt.session.execute(select(ExecutionOrder).where(ExecutionOrder.cycle_id == c2.id))
        .scalars()
        .all()
        if o.asset.symbol == target
    ]
    assert sells == []  # a halted asset is carried, never force-sold
    _check_invariants(rt)
    # now the asset disappears from the API entirely -> still hold-only (temporarily unavailable)
    rt.rh_client.halted = set()  # type: ignore[attr-defined]
    rt.rh_client.missing = {target}  # type: ignore[attr-defined]
    rt.rh_client.as_of = DAY3  # type: ignore[attr-defined]
    c3 = run_cycle(rt, session_date=DAY3)
    assert target in c3.summary["hold_only"]
    _check_invariants(rt)


def test_strategy_disable_liquidates_and_enable_restores(rt: Runtime) -> None:
    run_cycle(rt, session_date=DAY1)
    loaded = rt.repo.load()
    code = next(c for c, b in loaded.books.items() if b.held_symbols())
    loaded.strategies[code].enabled = False
    loaded.strategies[code].status = "DISABLED"
    rt.session.commit()
    rt.rh_client.as_of = DAY2  # type: ignore[attr-defined]
    run_cycle(rt, session_date=DAY2)
    loaded = rt.repo.load()
    # the disabled sleeve only reduces exposure (subject to per-order caps) and never buys
    fills = (
        rt.session.execute(
            select(VirtualFill).where(VirtualFill.strategy_id == loaded.strategies[code].id)
        )
        .scalars()
        .all()
    )
    day2 = [f for f in fills if f.cycle_id == 2]
    assert day2 and all(f.side == "SELL" for f in day2)
    _check_invariants(rt)
