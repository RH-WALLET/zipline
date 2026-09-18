"""The daily cycle, valuation and reconciliation jobs.

One cycle per completed regular US-equity session:

  universe -> historical bars -> live prices -> treasury -> capital allocation
  -> strategy signals & targets -> netting (internal crosses + net orders)
  -> execution (dry-run or onchain) -> marking & snapshots -> reconciliation
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from zipline_engine.accounting.allocation import distribute
from zipline_engine.accounting.books import Book
from zipline_engine.accounting.netting import NettingResult, RiskLimits, plan
from zipline_engine.accounting.repository import LoadedBooks
from zipline_engine.accounting.status import evaluate_status
from zipline_engine.core.calendar import last_completed_session, next_cycle_time, session_index
from zipline_engine.core.money import ZERO, D, q_money
from zipline_engine.core.system import get_state, turnover_today
from zipline_engine.db.enums import (
    CycleStatus,
    EventLevel,
    EventType,
    FillKind,
    Side,
    StrategyStatus,
)
from zipline_engine.db.models import Asset, Cycle, InternalCross, StrategySignal
from zipline_engine.execution.pipeline import ExecutionPipeline, ExecutionSummary
from zipline_engine.logging_setup import redact
from zipline_engine.robinhood.pricing import RefPrice
from zipline_engine.runtime import LiveTradingBlocked, Runtime, build_adapter
from zipline_engine.scheduler.bootstrap import (
    ensure_strategy_rows,
    ensure_version,
    load_strategy_impl,
)
from zipline_engine.strategies.base import StrategyContext
from zipline_engine.treasury.backends import TreasuryBalances
from zipline_engine.treasury.service import TreasuryValuation

log = logging.getLogger(__name__)


class CycleError(RuntimeError):
    pass


@dataclass
class MarketState:
    assets: list[Asset]
    eligible: list[str]
    hold_only: set[str]
    prices: dict[str, RefPrice]
    token_prices: dict[str, Decimal]
    balances: TreasuryBalances
    valuation: TreasuryValuation
    notes: list[str] = field(default_factory=list)


def _token_prices(prices: dict[str, RefPrice]) -> dict[str, Decimal]:
    return {s: rp.token_mid for s, rp in prices.items() if rp.token_mid > 0}


def risk_limits(rt: Runtime) -> RiskLimits:
    s = rt.settings
    return RiskLimits(
        max_single_asset_pct=s.max_single_asset_pct,
        max_order_pct_of_treasury=s.max_order_pct_of_treasury,
        max_daily_turnover_pct=s.max_daily_turnover_pct,
        min_trade_notional_pct=s.min_trade_notional_pct,
        cash_reserve_pct=s.cash_reserve_pct,
    )


# --------------------------------------------------------------------------- market state


def observe_market(
    rt: Runtime, *, refresh_universe: bool, cycle_id: int | None = None
) -> MarketState:
    """Universe + live prices + treasury balances + valuation (no trading)."""
    notes: list[str] = []
    if refresh_universe:
        report = rt.universe.refresh()
        if report.error:
            notes.append(report.error)
        st = get_state(rt.session)
        st.last_universe_refresh_at = datetime.now(UTC)
    assets = rt.universe.all_assets()
    eligible = sorted(a.symbol for a in assets if a.eligible)
    hold_only = {
        a.symbol
        for a in assets
        if (not a.eligible) and "hold_only" in (a.eligibility_reasons or [])
    }
    balances = rt.treasury.read_balances(assets)
    priced_symbols = (
        set(eligible) | set(balances.positions) | {a.symbol for a in assets if a.in_allowlist}
    )
    prices = rt.pricing.snapshot([a for a in assets if a.symbol in priced_symbols])
    valuation = rt.treasury.value(balances, prices)
    # a held asset without any price is hold-only by definition
    for sym in valuation.missing_prices:
        hold_only.add(sym)
    return MarketState(
        assets, eligible, hold_only, prices, _token_prices(prices), balances, valuation, notes
    )


# --------------------------------------------------------------------------- capital


def allocate_pending_funding(rt: Runtime, loaded: LoadedBooks, cycle_id: int | None) -> Decimal:
    total = ZERO
    for ev in rt.funding.unallocated_events():
        outcome = rt.allocator.allocate(
            D(ev.amount), loaded.strategies, loaded.books, loaded.weights_pct
        )
        rt.funding.mark_allocated(ev, outcome)
        total += D(ev.amount)
        rt.events.emit(
            EventType.TREASURY_UPDATED,
            f"allocated {q_money(ev.amount)} {ev.asset_symbol} from {ev.kind}: {len(outcome.to_sleeves)} sleeves, reserve {outcome.to_reserve}",
            payload={
                "funding_event": ev.id,
                "to_sleeves": {k: str(v) for k, v in outcome.to_sleeves.items()},
                "to_reserve": str(outcome.to_reserve),
            },
            cycle_id=cycle_id,
        )
    return total


def rebalance_reserve(
    rt: Runtime, loaded: LoadedBooks, valuation: TreasuryValuation, cycle_id: int | None
) -> None:
    """Keep treasury buffer cash (cash not owned by sleeves) near the configured reserve."""
    nav = valuation.nav
    if nav <= 0:
        return
    sleeve_cash = sum((b.cash for b in loaded.books.values()), ZERO)
    buffer = valuation.cash - sleeve_cash
    target = valuation.reserve_target
    band = nav * Decimal("0.01")
    if buffer > target + band:
        excess = q_money(buffer - target)
        weights = rt.allocator.policy.target_weights(
            rt.allocator.sleeve_infos(loaded.strategies, loaded.books, loaded.weights_pct)
        )
        parts = distribute(excess, weights)
        for code, amt in parts.items():
            loaded.books[code].add_capital(amt)
        if parts:
            rt.events.emit(
                EventType.TREASURY_UPDATED,
                f"reserve excess {excess} redistributed to {len(parts)} sleeves",
                payload={k: str(v) for k, v in parts.items()},
                cycle_id=cycle_id,
            )
    elif buffer < target - band:
        shortfall = q_money(target - buffer)
        cash_weights = {c: b.cash for c, b in loaded.books.items() if b.cash > 0}
        taken: dict[str, Decimal] = {}
        for code, amt in distribute(
            min(shortfall, sum(cash_weights.values(), ZERO)), cash_weights
        ).items():
            taken[code] = loaded.books[code].remove_capital(amt)
        if taken:
            rt.events.emit(
                EventType.TREASURY_UPDATED,
                f"reserve shortfall {shortfall}: {q_money(sum(taken.values(), ZERO))} pulled from sleeve cash",
                payload={k: str(v) for k, v in taken.items()},
                cycle_id=cycle_id,
            )


# --------------------------------------------------------------------------- strategies


@dataclass
class StrategyRun:
    code: str
    targets: dict[str, Decimal]
    signals_count: int
    notes: list[str]
    version_hash: str


def run_strategies(
    rt: Runtime, loaded: LoadedBooks, market: MarketState, session_date: date, cycle_id: int
) -> tuple[dict[str, dict[str, Decimal]], list[StrategyRun]]:
    panel = rt.marketdata.load_panel(
        sorted(set(rt.settings.allowlist) | set(market.eligible)), session_date
    )
    ordinal = session_index(session_date)
    benchmark = "SPY" if "SPY" in market.eligible else None
    targets: dict[str, dict[str, Decimal]] = {}
    runs: list[StrategyRun] = []
    asset_ids = {a.symbol: a.id for a in market.assets}
    for code, row in loaded.strategies.items():
        book = loaded.books[code]
        state_row = loaded.states[code]
        if not row.enabled or row.status == StrategyStatus.DISABLED:
            targets[code] = {}
            runs.append(
                StrategyRun(
                    code, {}, 0, ["disabled: liquidating to cash"], row.current_version_hash or ""
                )
            )
            continue
        impl = load_strategy_impl(rt, row)
        version = ensure_version(rt, row, impl)
        params = dict(impl.params)
        if code == "PAIRS":
            params["pairs"] = [list(p) for p in rt.settings.pairs]
            impl = type(impl)(params)
            version = ensure_version(rt, row, impl)
        ctx = StrategyContext(
            session_date=session_date,
            universe=list(market.eligible),
            panel=panel,
            current_weights=book.weights(market.token_prices),
            state=dict(book.state),
            params=impl.params,
            benchmark=benchmark,
            session_ordinal=ordinal,
        )
        try:
            out = impl.run(ctx)
        except Exception as e:
            rt.events.emit(
                EventType.STRATEGY_CYCLE_FAILED,
                f"{code}: {type(e).__name__}: {redact(str(e))}",
                level=EventLevel.ERROR,
                cycle_id=cycle_id,
            )
            targets[code] = book.weights(market.token_prices)  # hold current book on error
            runs.append(
                StrategyRun(
                    code, targets[code], 0, [f"error: {type(e).__name__}"], version.version_hash
                )
            )
            continue
        book.state = out.new_state
        prev = ctx.current_weights
        for sig in out.signals:
            rt.session.add(
                StrategySignal(
                    cycle_id=cycle_id,
                    strategy_id=row.id,
                    asset_id=asset_ids.get(sig.symbol) if sig.symbol else None,
                    session_date=session_date,
                    kind=sig.kind,
                    value=D(sig.value) if sig.value is not None else None,
                    target_weight=out.target_weights.get(sig.symbol, ZERO) if sig.symbol else ZERO,
                    previous_weight=prev.get(sig.symbol, ZERO) if sig.symbol else ZERO,
                    version_hash=version.version_hash,
                    details=_jsonable(sig.details),
                )
            )
        rt.session.add(
            StrategySignal(
                cycle_id=cycle_id,
                strategy_id=row.id,
                asset_id=None,
                session_date=session_date,
                kind="TARGETS",
                value=sum(out.target_weights.values(), ZERO),
                target_weight=sum(out.target_weights.values(), ZERO),
                previous_weight=sum(prev.values(), ZERO),
                version_hash=version.version_hash,
                details={
                    "targets": {k: str(v) for k, v in out.target_weights.items()},
                    "previous": {k: str(v) for k, v in prev.items()},
                    "notes": out.notes,
                    "universe": list(market.eligible),
                },
            )
        )
        state_row.signals_count = int(state_row.signals_count or 0) + len(out.signals)
        targets[code] = out.target_weights
        runs.append(
            StrategyRun(code, out.target_weights, len(out.signals), out.notes, version.version_hash)
        )
        rt.events.emit(
            EventType.STRATEGY_SIGNAL_CREATED,
            f"{code}: {len(out.signals)} signals -> targets {{{', '.join(f'{k} {float(v):.1%}' for k, v in out.target_weights.items()) or 'cash'}}}",
            payload={
                "strategy": code,
                "targets": {k: str(v) for k, v in out.target_weights.items()},
                "notes": out.notes,
                "version": version.version_hash,
            },
            cycle_id=cycle_id,
        )
    rt.session.flush()
    return targets, runs


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    from zipline_engine.events.bus import _jsonable as j

    return j(d)


# --------------------------------------------------------------------------- netting & crosses


def apply_internal_crosses(
    rt: Runtime, loaded: LoadedBooks, result: NettingResult, cycle_id: int
) -> int:
    n = 0
    for c in result.crosses:
        asset = loaded.asset_by_symbol.get(c.symbol)
        if asset is None:
            continue
        row = InternalCross(
            cycle_id=cycle_id,
            asset_id=asset.id,
            buyer_strategy_id=loaded.strategies[c.buyer].id,
            seller_strategy_id=loaded.strategies[c.seller].id,
            quantity=c.quantity,
            price=c.price,
            notional=q_money(c.notional),
            reference_price_source="robinhood_mid_x_multiplier",
        )
        rt.session.add(row)
        rt.session.flush()
        sell = loaded.books[c.seller].apply_fill(c.symbol, Side.SELL, c.quantity, c.price)
        buy = loaded.books[c.buyer].apply_fill(c.symbol, Side.BUY, c.quantity, c.price)
        rt.repo.record_fill(
            strategy=loaded.strategies[c.seller],
            asset=asset,
            fill=sell,
            kind=FillKind.INTERNAL_CROSS,
            cycle_id=cycle_id,
            internal_cross_id=row.id,
        )
        rt.repo.record_fill(
            strategy=loaded.strategies[c.buyer],
            asset=asset,
            fill=buy,
            kind=FillKind.INTERNAL_CROSS,
            cycle_id=cycle_id,
            internal_cross_id=row.id,
        )
        rt.events.emit(
            EventType.INTERNAL_CROSS,
            f"INTERNAL_CROSS {c.quantity:.6f} {c.symbol} {c.seller} -> {c.buyer} @ {c.price:.6f} (no onchain transaction)",
            payload={
                "symbol": c.symbol,
                "buyer": c.buyer,
                "seller": c.seller,
                "quantity": str(c.quantity),
                "price": str(c.price),
            },
            cycle_id=cycle_id,
        )
        n += 1
    return n


# --------------------------------------------------------------------------- marking


def mark_and_save(
    rt: Runtime, loaded: LoadedBooks, market: MarketState, cycle_id: int | None, *, snapshot: bool
) -> None:
    now = datetime.now(UTC)
    for code, book in loaded.books.items():
        row = loaded.strategies[code]
        val = book.mark(market.token_prices)
        new_status, reason = evaluate_status(
            enabled=row.enabled,
            current_status=row.status,
            drawdown_pct=val.drawdown_pct,
            watch_drawdown_pct=rt.settings.watch_drawdown_pct,
            disable_drawdown_pct=rt.settings.disable_drawdown_pct,
        )
        if new_status == StrategyStatus.DISABLED and row.enabled and "drawdown" in reason:
            row.enabled = False  # sticky auto-disable; operator must re-enable
        if new_status != row.status:
            rt.events.emit(
                EventType.STRATEGY_STATUS_CHANGED,
                f"{code}: {row.status} -> {new_status} ({reason})",
                level=EventLevel.WARN if new_status != StrategyStatus.ACTIVE else EventLevel.INFO,
                payload={
                    "strategy": code,
                    "from": row.status,
                    "to": str(new_status),
                    "reason": reason,
                },
                cycle_id=cycle_id,
            )
            row.status = str(new_status)
            row.status_reason = reason
        rt.repo.save(
            book,
            row,
            loaded.states[code],
            val,
            market.token_prices,
            loaded.asset_by_symbol,
            cycle_id,
        )
        if snapshot:
            rt.repo.snapshot(book, row, val, market.token_prices, taken_at=now)
    if snapshot:
        rt.treasury.take_snapshot(market.valuation, loaded.books, taken_at=now)
    rt.session.flush()


# --------------------------------------------------------------------------- jobs


def run_valuation(rt: Runtime, *, refresh_universe: bool = False) -> TreasuryValuation:
    ensure_strategy_rows(rt)
    market = observe_market(rt, refresh_universe=refresh_universe)
    loaded = rt.repo.load()
    allocate_pending_funding(rt, loaded, None)
    mark_and_save(rt, loaded, market, None, snapshot=True)
    rt.events.emit(
        EventType.TREASURY_UPDATED,
        f"valuation: NAV {market.valuation.nav:.2f} cash {market.valuation.cash:.2f} positions {market.valuation.positions_value:.2f} ({market.balances.source})",
        payload={
            "nav": str(market.valuation.nav),
            "cash": str(market.valuation.cash),
            "positions_value": str(market.valuation.positions_value),
            "source": market.balances.source,
        },
    )
    return market.valuation


def run_reconciliation(rt: Runtime, trigger: str = "scheduled") -> Any:
    market = observe_market(rt, refresh_universe=False)
    loaded = rt.repo.load()
    return rt.reconciler.run(
        loaded.books,
        market.balances,
        market.token_prices,
        nav=market.valuation.nav,
        reserve_target=market.valuation.reserve_target,
        trigger=trigger,
    )


def run_cycle(rt: Runtime, *, force: bool = False, session_date: date | None = None) -> Cycle:
    session = rt.session
    st = get_state(session)
    if st.paused:
        raise CycleError(f"system is paused: {st.pause_reason}")
    session_date = session_date or last_completed_session()
    existing = (
        session.execute(
            select(Cycle).where(
                Cycle.session_date == session_date, Cycle.status == str(CycleStatus.COMPLETED)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None and not force:
        log.info(
            "cycle for %s already completed (id=%s); use force to rerun", session_date, existing.id
        )
        return existing
    ensure_strategy_rows(rt)
    mode = "LIVE" if rt.settings.live_trading else "DRY_RUN"
    cycle = Cycle(session_date=session_date, mode=mode, status=str(CycleStatus.RUNNING))
    session.add(cycle)
    session.flush()
    rt.events.emit(
        EventType.STRATEGY_CYCLE_STARTED,
        f"cycle {cycle.id} for session {session_date} ({mode})",
        payload={"session_date": session_date.isoformat(), "mode": mode},
        cycle_id=cycle.id,
    )
    session.commit()
    try:
        summary = _run_cycle_body(rt, cycle, session_date)
        cycle.status = str(CycleStatus.COMPLETED)
        cycle.finished_at = datetime.now(UTC)
        cycle.summary = summary
        st = get_state(session)
        st.last_cycle_id = cycle.id
        st.last_cycle_at = cycle.finished_at
        st.next_cycle_at = next_cycle_time(rt.settings.cycle_time_et)
        rt.events.emit(
            EventType.STRATEGY_CYCLE_COMPLETED,
            f"cycle {cycle.id} completed: {summary.get('net_orders', 0)} net orders, {summary.get('internal_crosses', 0)} internal crosses, {summary.get('filled', 0)} fills",
            payload=summary,
            cycle_id=cycle.id,
        )
        session.commit()
    except Exception as e:
        session.rollback()
        cycle = session.get(Cycle, cycle.id) or cycle
        cycle.status = str(CycleStatus.FAILED)
        cycle.finished_at = datetime.now(UTC)
        cycle.error = redact(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")[:8000]
        rt.events.emit(
            EventType.STRATEGY_CYCLE_FAILED,
            f"cycle {cycle.id} failed: {type(e).__name__}: {redact(str(e))}",
            level=EventLevel.ERROR,
            cycle_id=cycle.id,
        )
        session.commit()
        raise
    return cycle


def _run_cycle_body(rt: Runtime, cycle: Cycle, session_date: date) -> dict[str, Any]:
    session = rt.session
    # 1. universe, prices, treasury
    market = observe_market(rt, refresh_universe=True, cycle_id=cycle.id)
    for note in market.notes:
        rt.events.emit(EventType.CONFIG_WARNING, note, level=EventLevel.WARN, cycle_id=cycle.id)
    # 2. historical data
    report = rt.marketdata.refresh(
        sorted(set(rt.settings.allowlist) | set(market.eligible)), session_date
    )
    rt.events.emit(
        EventType.MARKET_DATA_UPDATED,
        f"history ({report.provider}): {report.total_new_bars} new bars, {len(report.unchanged)} unchanged, {len(report.failed)} failed",
        level=EventLevel.WARN if report.failed else EventLevel.INFO,
        payload={
            "provider": report.provider,
            "fetched": report.fetched,
            "unchanged": report.unchanged,
            "failed": report.failed,
            "unavailable": report.unavailable,
            "kind": "UNDERLYING_EQUITY_DAILY",
        },
        cycle_id=cycle.id,
    )
    get_state(session).last_market_data_at = datetime.now(UTC)
    # 3. books & capital
    loaded = rt.repo.load()
    allocate_pending_funding(rt, loaded, cycle.id)
    rebalance_reserve(rt, loaded, market.valuation, cycle.id)
    for book in loaded.books.values():
        book.mark(market.token_prices)  # pre-trade mark: market moves since the last valuation
    cycle.nav_at_start = market.valuation.nav
    session.commit()
    # 4. strategies
    targets, runs = run_strategies(rt, loaded, market, session_date, cycle.id)
    # 5. netting
    result = plan(
        targets,
        loaded.books,
        market.token_prices,
        hold_only=market.hold_only,
        treasury_nav=market.valuation.nav,
        treasury_cash=market.valuation.cash,
        treasury_positions=market.balances.positions,
        limits=risk_limits(rt),
        turnover_today=turnover_today(session, session_date),
    )
    for note in result.risk_notes:
        rt.events.emit(EventType.RISK_LIMIT_APPLIED, note, level=EventLevel.WARN, cycle_id=cycle.id)
    crosses = apply_internal_crosses(rt, loaded, result, cycle.id)
    rt.events.emit(
        EventType.TARGETS_AGGREGATED,
        f"aggregated targets over {len(result.aggregate_targets)} assets: {len(result.sleeve_deltas)} sleeve deltas -> {crosses} internal crosses, {len(result.net_orders)} net external orders ({result.gross_external_notional:.2f} gross)",
        payload={
            "aggregate_targets": {k: str(q_money(v)) for k, v in result.aggregate_targets.items()},
            "net_orders": [
                {
                    "symbol": o.symbol,
                    "side": str(o.side),
                    "quantity": str(o.quantity),
                    "notional": str(q_money(o.notional)),
                    "participants": [
                        {"strategy": p.code, "quantity": str(p.quantity)} for p in o.participants
                    ],
                    "notes": o.notes,
                }
                for o in result.net_orders
            ],
            "dropped": [
                {
                    "strategy": d.code,
                    "symbol": d.symbol,
                    "quantity": str(d.quantity),
                    "reason": d.reason,
                }
                for d in result.dropped
            ],
            "sleeve_navs": {k: str(q_money(v)) for k, v in result.sleeve_navs.items()},
        },
        cycle_id=cycle.id,
    )
    session.commit()
    # 6. execution
    exec_summary = ExecutionSummary()
    if result.net_orders:
        try:
            adapter = build_adapter(rt, market.prices)
        except LiveTradingBlocked as e:
            rt.events.emit(
                EventType.EXECUTION_FAILED,
                f"LIVE_TRADING requested but blocked: {e}. No orders were sent.",
                level=EventLevel.ERROR,
                cycle_id=cycle.id,
            )
            adapter = None
        if adapter is not None:
            pipeline = ExecutionPipeline(
                session,
                rt.settings,
                rt.events,
                adapter,
                rt.repo,
                simulated=rt.simulated,
                eth_usd=market.valuation.eth_usd,
            )
            exec_summary = pipeline.run(
                cycle_id=cycle.id,
                session_date=session_date,
                orders=result.net_orders,
                books=loaded.books,
                strategies=loaded.strategies,
                asset_by_symbol=loaded.asset_by_symbol,
                prices=market.prices,
                treasury=market.balances,
                treasury_nav=market.valuation.nav,
                hold_only=market.hold_only,
            )
    # 7. post-trade marking, snapshots
    post = observe_market(rt, refresh_universe=False, cycle_id=cycle.id)
    for state_row in loaded.states.values():
        state_row.last_rebalance_at = datetime.now(UTC)
    mark_and_save(rt, loaded, post, cycle.id, snapshot=True)
    rt.events.emit(
        EventType.TREASURY_UPDATED,
        f"post-cycle: NAV {post.valuation.nav:.2f} cash {post.valuation.cash:.2f} positions {post.valuation.positions_value:.2f}",
        payload={
            "nav": str(post.valuation.nav),
            "cash": str(post.valuation.cash),
            "positions_value": str(post.valuation.positions_value),
            "gas_eth": str(post.valuation.gas_eth),
        },
        cycle_id=cycle.id,
    )
    session.commit()
    # 8. reconciliation
    rt.reconciler.run(
        loaded.books,
        post.balances,
        post.token_prices,
        nav=post.valuation.nav,
        reserve_target=post.valuation.reserve_target,
        trigger=f"cycle {cycle.id}",
    )
    session.commit()
    return {
        "session_date": session_date.isoformat(),
        "eligible": market.eligible,
        "hold_only": sorted(market.hold_only),
        "history_new_bars": report.total_new_bars,
        "strategies_run": len(runs),
        "signals": sum(r.signals_count for r in runs),
        "sleeve_deltas": len(result.sleeve_deltas),
        "internal_crosses": crosses,
        "net_orders": len(result.net_orders),
        "gross_internal_notional": str(q_money(result.gross_internal_notional)),
        "gross_external_notional": str(q_money(result.gross_external_notional)),
        "submitted": exec_summary.submitted,
        "filled": exec_summary.filled,
        "rejected": exec_summary.rejected,
        "failed": exec_summary.failed,
        "nav_start": str(market.valuation.nav),
        "nav_end": str(post.valuation.nav),
        "mode": cycle.mode,
    }


def book_summary(book: Book, prices: dict[str, Decimal]) -> dict[str, str]:
    return {"nav": str(q_money(book.nav(prices))), "cash": str(q_money(book.cash))}
