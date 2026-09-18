"""Read-only endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from zipline_engine import __version__
from zipline_engine.api import serializers as ser
from zipline_engine.api.deps import db, settings
from zipline_engine.config import Settings
from zipline_engine.core.calendar import last_completed_session, next_cycle_time
from zipline_engine.core.money import ZERO, D, q_money
from zipline_engine.core.system import get_state
from zipline_engine.db.models import (
    Asset,
    BlockchainTransaction,
    Cycle,
    ExecutionOrder,
    FundingEvent,
    InternalCross,
    PriceSnapshot,
    ReconciliationEvent,
    Strategy,
    StrategyAllocation,
    StrategyPosition,
    StrategySignal,
    StrategyState,
    StrategyVersion,
    SystemEvent,
    TreasurySnapshot,
    WithdrawalEvent,
)

router = APIRouter()


def _mode(cfg: Settings, session: Session) -> dict[str, Any]:
    st = get_state(session)
    return {
        "live_trading": cfg.live_trading,
        "demo": not cfg.live_trading,
        "treasury_mode": cfg.treasury_mode,
        "execution_mode": "LIVE" if cfg.live_trading else "DRY_RUN",
        "paused": st.paused,
        "pause_reason": st.pause_reason,
        "labels": [] if cfg.live_trading else ["DEMO MODE", "LIVE TRADING DISABLED"],
    }


@router.get("/health")
def health(session: Session = Depends(db)) -> dict[str, Any]:
    try:
        session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "time": datetime.now(UTC).isoformat(),
        "version": __version__,
    }


@router.get("/status")
def status_(session: Session = Depends(db), cfg: Settings = Depends(settings)) -> dict[str, Any]:
    import zipline

    st = get_state(session)
    strategies = session.execute(select(Strategy)).scalars().all()
    positions = session.execute(
        select(func.count()).select_from(StrategyPosition).where(StrategyPosition.quantity > 0)
    ).scalar_one()
    executions = session.execute(select(func.count()).select_from(ExecutionOrder)).scalar_one()
    real_txs = session.execute(select(func.count()).select_from(BlockchainTransaction)).scalar_one()
    last_cycle = session.get(Cycle, st.last_cycle_id) if st.last_cycle_id else None
    from zipline_engine.runtime import live_blockers

    blockers: list[str] = cfg.live_trading_blockers()
    if st.paused:
        blockers.append(f"system is paused: {st.pause_reason}")
    try:
        next_cycle = next_cycle_time(cfg.cycle_time_et).isoformat()
    except Exception:
        next_cycle = None
    _ = live_blockers  # imported for parity with the worker; the API does not open RPC connections
    return {
        "mode": _mode(cfg, session),
        "chain": {
            "chain_id": cfg.chain_id,
            "explorer_base_url": cfg.explorer_base_url,
            "rpc_configured": bool(cfg.rh_rpc_url),
            "wallet_address": cfg.executor_address or None,
            "cash_token": {
                "symbol": cfg.cash_token_symbol,
                "address": cfg.cash_token_address or None,
            },
        },
        "system": {
            "paused": st.paused,
            "pause_reason": st.pause_reason,
            "paused_at": ser.j(st.paused_at),
            "consecutive_failed_txs": st.consecutive_failed_txs,
            "bootstrapped_at": ser.j(st.bootstrapped_at),
            "last_cycle": ser.cycle(last_cycle) if last_cycle else None,
            "last_cycle_at": ser.j(st.last_cycle_at),
            "next_cycle_at": next_cycle,
            "last_completed_session": last_completed_session().isoformat(),
            "last_reconciliation_status": st.last_reconciliation_status,
            "last_reconciliation_at": ser.j(st.last_reconciliation_at),
            "last_market_data_at": ser.j(st.last_market_data_at),
            "last_universe_refresh_at": ser.j(st.last_universe_refresh_at),
            "cycle_time_et": cfg.cycle_time_et,
        },
        "counts": {
            "strategies": len(strategies),
            "active_strategies": sum(1 for s in strategies if s.status == "ACTIVE"),
            "watch_strategies": sum(1 for s in strategies if s.status == "WATCH"),
            "disabled_strategies": sum(1 for s in strategies if s.status == "DISABLED"),
            "positions": positions,
            "executions": executions,
            "real_transactions": real_txs,
        },
        "live_trading_blockers": blockers,
        "config": cfg.public_dict(),
        "software": {
            "engine": __version__,
            "zipline_reloaded": getattr(zipline, "__version__", "unknown"),
        },
    }


def _return_metrics(snap: TreasurySnapshot | None) -> dict[str, Any]:
    if snap is None:
        return {"total_return_pct": None, "trading_pnl": None}
    nav = D(snap.nav)
    net_external = D(snap.base_capital) + D(snap.contributions_total) - D(snap.withdrawals_total)
    trading_pnl = nav - net_external
    twr = D(snap.twr_index)
    return {
        "total_return_pct": str(((twr - 1) * 100).quantize(Decimal("0.0001"))),
        "simple_return_pct": str(((trading_pnl / net_external) * 100).quantize(Decimal("0.0001")))
        if net_external > 0
        else None,
        "trading_pnl": str(q_money(trading_pnl)),
        "net_external_capital": str(q_money(net_external)),
    }


@router.get("/treasury")
def treasury(session: Session = Depends(db), cfg: Settings = Depends(settings)) -> dict[str, Any]:
    snap = session.execute(
        select(TreasurySnapshot).order_by(TreasurySnapshot.taken_at.desc()).limit(1)
    ).scalar_one_or_none()
    active = session.execute(
        select(func.count()).select_from(Strategy).where(Strategy.status != "DISABLED")
    ).scalar_one()
    positions_rows = session.execute(
        select(StrategyPosition, Asset.symbol)
        .join(Asset, Asset.id == StrategyPosition.asset_id)
        .where(StrategyPosition.quantity > 0)
    ).all()
    holdings: dict[str, dict[str, Decimal]] = {}
    for pos, sym in positions_rows:
        h = holdings.setdefault(
            sym,
            {"quantity": ZERO, "cost_basis": ZERO, "market_value": ZERO, "unrealized_pnl": ZERO},
        )
        h["quantity"] += D(pos.quantity)
        h["cost_basis"] += D(pos.cost_basis)
        h["market_value"] += D(pos.market_value)
        h["unrealized_pnl"] += D(pos.unrealized_pnl)
    return {
        "mode": _mode(cfg, session),
        "wallet_address": cfg.executor_address or None,
        "explorer_address_url": f"{cfg.explorer_base_url.rstrip('/')}/address/{cfg.executor_address}"
        if cfg.executor_address
        else None,
        "cash_token": {"symbol": cfg.cash_token_symbol, "address": cfg.cash_token_address or None},
        "snapshot": ser.treasury_snapshot(snap) if snap else None,
        "returns": _return_metrics(snap),
        "active_strategies": active,
        "holdings": {
            k: {kk: str(q_money(vv)) if kk != "quantity" else str(vv) for kk, vv in v.items()}
            for k, v in sorted(holdings.items())
        },
        "treasury_positions": snap.positions if snap else {},
    }


@router.get("/treasury/history")
def treasury_history(
    limit: int = Query(500, le=5000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(TreasurySnapshot).order_by(TreasurySnapshot.taken_at.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [ser.treasury_snapshot(r) for r in reversed(rows)]


@router.get("/treasury/funding")
def treasury_funding(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    funding = session.execute(select(FundingEvent).order_by(FundingEvent.id.desc())).scalars().all()
    withdrawals = (
        session.execute(select(WithdrawalEvent).order_by(WithdrawalEvent.id.desc())).scalars().all()
    )
    return {
        "funding": [ser.funding(f, cfg.explorer_base_url) for f in funding],
        "withdrawals": [ser.withdrawal(w, cfg.explorer_base_url) for w in withdrawals],
    }


@router.get("/assets")
def assets(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> list[dict[str, Any]]:
    rows = session.execute(select(Asset).order_by(Asset.symbol)).scalars().all()
    out = []
    for a in rows:
        price = session.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.asset_id == a.id)
            .order_by(PriceSnapshot.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        d = ser.asset(a, price, cfg.chain_id)
        dep = d["deployment"]
        d["explorer_token_url"] = (
            f"{cfg.explorer_base_url.rstrip('/')}/token/{dep['contract_address']}" if dep else None
        )
        out.append(d)
    return out


def _strategy_summary(session: Session, s: Strategy, cfg: Settings) -> dict[str, Any]:
    st = session.execute(
        select(StrategyState).where(StrategyState.strategy_id == s.id)
    ).scalar_one_or_none()
    alloc = session.execute(
        select(StrategyAllocation).where(
            StrategyAllocation.strategy_id == s.id, StrategyAllocation.active.is_(True)
        )
    ).scalar_one_or_none()
    positions = session.execute(
        select(StrategyPosition, Asset.symbol)
        .join(Asset, Asset.id == StrategyPosition.asset_id)
        .where(StrategyPosition.strategy_id == s.id, StrategyPosition.quantity > 0)
        .order_by(StrategyPosition.market_value.desc())
    ).all()
    d = ser.row(s)
    d["weight_pct"] = str(alloc.weight_pct) if alloc else None
    d["allocation_policy"] = alloc.policy if alloc else None
    d["state"] = ser.row(st, exclude={"state"}) if st else None
    if st is not None:
        twr = D(st.twr_index or 1)
        d["return_pct"] = str(((twr - 1) * 100).quantize(Decimal("0.0001")))
        d["total_pnl"] = str(q_money(D(st.realized_pnl) + D(st.unrealized_pnl)))
        d["age_days"] = (
            (datetime.now(UTC) - st.inception_at.astimezone(UTC)).days if st.inception_at else None
        )
    d["positions"] = [
        {"symbol": sym, **ser.row(p, exclude={"strategy_id"})} for p, sym in positions
    ]
    d["position_symbols"] = [sym for _, sym in positions]
    return d


@router.get("/strategies")
def strategies(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> list[dict[str, Any]]:
    rows = session.execute(select(Strategy).order_by(Strategy.id)).scalars().all()
    return [_strategy_summary(session, s, cfg) for s in rows]


def _get_strategy(session: Session, code: str) -> Strategy:
    s = session.execute(select(Strategy).where(Strategy.code == code.upper())).scalar_one_or_none()
    if s is None:
        try:
            s = session.get(Strategy, int(code))
        except ValueError:
            s = None
    if s is None:
        raise HTTPException(404, f"unknown strategy {code}")
    return s


@router.get("/strategies/{code}")
def strategy_detail(
    code: str, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    s = _get_strategy(session, code)
    d = _strategy_summary(session, s, cfg)
    versions = (
        session.execute(
            select(StrategyVersion)
            .where(StrategyVersion.strategy_id == s.id)
            .order_by(StrategyVersion.id.desc())
        )
        .scalars()
        .all()
    )
    d["versions"] = [ser.row(v) for v in versions]
    current = next(
        (v for v in versions if v.version_hash == s.current_version_hash),
        versions[0] if versions else None,
    )
    d["rules"] = current.rules if current else None
    d["params"] = current.params if current else None
    d["source_hash"] = current.source_hash if current else None
    st = session.execute(
        select(StrategyState).where(StrategyState.strategy_id == s.id)
    ).scalar_one_or_none()
    public_state = (
        {k: v for k, v in (st.state or {}).items() if not k.startswith("_")} if st else {}
    )
    d["persisted_state"] = ser.j(public_state)
    d["provenance"] = ["NO AI", "DETERMINISTIC", "REPRODUCIBLE", "RULE-BASED"]
    return d


@router.get("/strategies/{code}/positions")
def strategy_positions(
    code: str, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> list[dict[str, Any]]:
    s = _get_strategy(session, code)
    return _strategy_summary(session, s, cfg)["positions"]


@router.get("/strategies/{code}/history")
def strategy_history(
    code: str, limit: int = Query(500, le=5000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    from zipline_engine.db.models import PortfolioSnapshot

    s = _get_strategy(session, code)
    rows = (
        session.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.strategy_id == s.id)
            .order_by(PortfolioSnapshot.taken_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [ser.portfolio_snapshot(r) for r in reversed(rows)]


def _symbol_map(session: Session) -> dict[int, str]:
    return {a.id: a.symbol for a in session.execute(select(Asset)).scalars().all()}


def _code_map(session: Session) -> dict[int, str]:
    return {s.id: s.code for s in session.execute(select(Strategy)).scalars().all()}


@router.get("/strategies/{code}/signals")
def strategy_signals(
    code: str, limit: int = Query(200, le=2000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    s = _get_strategy(session, code)
    rows = (
        session.execute(
            select(StrategySignal)
            .where(StrategySignal.strategy_id == s.id)
            .order_by(StrategySignal.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    sym = _symbol_map(session)
    return [ser.signal(r, sym.get(r.asset_id) if r.asset_id else None, s.code) for r in rows]


@router.get("/strategies/{code}/fills")
def strategy_fills(
    code: str, limit: int = Query(200, le=2000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    from zipline_engine.db.models import VirtualFill

    s = _get_strategy(session, code)
    rows = (
        session.execute(
            select(VirtualFill)
            .where(VirtualFill.strategy_id == s.id)
            .order_by(VirtualFill.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    sym = _symbol_map(session)
    return [ser.fill(r, sym.get(r.asset_id), s.code) for r in rows]


@router.get("/strategies/{code}/crosses")
def strategy_crosses(
    code: str, limit: int = Query(200, le=2000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    s = _get_strategy(session, code)
    rows = (
        session.execute(
            select(InternalCross)
            .where(
                (InternalCross.buyer_strategy_id == s.id)
                | (InternalCross.seller_strategy_id == s.id)
            )
            .order_by(InternalCross.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    sym, codes = _symbol_map(session), _code_map(session)
    return [
        ser.cross(
            r, sym.get(r.asset_id), codes.get(r.buyer_strategy_id), codes.get(r.seller_strategy_id)
        )
        for r in rows
    ]


@router.get("/strategies/{code}/executions")
def strategy_executions(
    code: str,
    limit: int = Query(200, le=2000),
    session: Session = Depends(db),
    cfg: Settings = Depends(settings),
) -> list[dict[str, Any]]:
    from zipline_engine.db.models import VirtualFill

    s = _get_strategy(session, code)
    order_ids = (
        session.execute(
            select(VirtualFill.execution_order_id)
            .where(VirtualFill.strategy_id == s.id, VirtualFill.execution_order_id.is_not(None))
            .distinct()
        )
        .scalars()
        .all()
    )
    if not order_ids:
        return []
    rows = (
        session.execute(
            select(ExecutionOrder)
            .where(ExecutionOrder.id.in_(order_ids))
            .order_by(ExecutionOrder.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    sym = _symbol_map(session)
    return [ser.order(o, sym.get(o.asset_id), cfg.explorer_base_url) for o in rows]


@router.get("/signals")
def signals(
    limit: int = Query(200, le=2000),
    strategy: str | None = None,
    cycle_id: int | None = None,
    session: Session = Depends(db),
) -> list[dict[str, Any]]:
    q = select(StrategySignal).order_by(StrategySignal.id.desc()).limit(limit)
    if cycle_id is not None:
        q = q.where(StrategySignal.cycle_id == cycle_id)
    if strategy:
        s = _get_strategy(session, strategy)
        q = q.where(StrategySignal.strategy_id == s.id)
    rows = session.execute(q).scalars().all()
    sym, codes = _symbol_map(session), _code_map(session)
    return [
        ser.signal(r, sym.get(r.asset_id) if r.asset_id else None, codes.get(r.strategy_id))
        for r in rows
    ]


@router.get("/executions")
def executions(
    limit: int = Query(200, le=2000),
    status: str | None = None,
    mode: str | None = None,
    session: Session = Depends(db),
    cfg: Settings = Depends(settings),
) -> list[dict[str, Any]]:
    q = select(ExecutionOrder).order_by(ExecutionOrder.id.desc()).limit(limit)
    if status:
        q = q.where(ExecutionOrder.status == status.upper())
    if mode:
        q = q.where(ExecutionOrder.mode == mode.upper())
    rows = session.execute(q).scalars().all()
    sym = _symbol_map(session)
    return [ser.order(o, sym.get(o.asset_id), cfg.explorer_base_url) for o in rows]


@router.get("/transactions")
def transactions(
    limit: int = Query(200, le=2000),
    session: Session = Depends(db),
    cfg: Settings = Depends(settings),
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(BlockchainTransaction).order_by(BlockchainTransaction.id.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [ser.transaction(t, cfg.explorer_base_url) for t in rows]


@router.get("/crosses")
def crosses(
    limit: int = Query(200, le=2000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    rows = (
        session.execute(select(InternalCross).order_by(InternalCross.id.desc()).limit(limit))
        .scalars()
        .all()
    )
    sym, codes = _symbol_map(session), _code_map(session)
    return [
        ser.cross(
            r, sym.get(r.asset_id), codes.get(r.buyer_strategy_id), codes.get(r.seller_strategy_id)
        )
        for r in rows
    ]


@router.get("/fills")
def fills(
    limit: int = Query(200, le=2000), kind: str | None = None, session: Session = Depends(db)
) -> list[dict[str, Any]]:
    from zipline_engine.db.models import VirtualFill

    q = select(VirtualFill).order_by(VirtualFill.id.desc()).limit(limit)
    if kind:
        q = q.where(VirtualFill.kind == kind.upper())
    rows = session.execute(q).scalars().all()
    sym, codes = _symbol_map(session), _code_map(session)
    return [ser.fill(r, sym.get(r.asset_id), codes.get(r.strategy_id)) for r in rows]


@router.get("/reconciliation")
def reconciliation(
    limit: int = Query(50, le=1000), session: Session = Depends(db)
) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(ReconciliationEvent).order_by(ReconciliationEvent.id.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    return [ser.reconciliation(r) for r in rows]


@router.get("/events")
def events(
    limit: int = Query(200, le=2000),
    after_id: int | None = None,
    type: str | None = None,
    level: str | None = None,
    session: Session = Depends(db),
) -> list[dict[str, Any]]:
    q = select(SystemEvent)
    if after_id is not None:
        q = q.where(SystemEvent.id > after_id).order_by(SystemEvent.id.asc())
    else:
        q = q.order_by(SystemEvent.id.desc())
    if type:
        q = q.where(SystemEvent.type == type.upper())
    if level:
        q = q.where(SystemEvent.level == level.upper())
    rows = session.execute(q.limit(limit)).scalars().all()
    return [ser.event(e) for e in rows]


@router.get("/cycles")
def cycles(limit: int = Query(50, le=1000), session: Session = Depends(db)) -> list[dict[str, Any]]:
    rows = session.execute(select(Cycle).order_by(Cycle.id.desc()).limit(limit)).scalars().all()
    return [ser.cycle(c) for c in rows]


@router.get("/cycles/{cycle_id}")
def cycle_detail(
    cycle_id: int, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    c = session.get(Cycle, cycle_id)
    if c is None:
        raise HTTPException(404, "unknown cycle")
    sym, codes = _symbol_map(session), _code_map(session)
    sigs = (
        session.execute(
            select(StrategySignal)
            .where(StrategySignal.cycle_id == c.id)
            .order_by(StrategySignal.id)
        )
        .scalars()
        .all()
    )
    xs = (
        session.execute(
            select(InternalCross).where(InternalCross.cycle_id == c.id).order_by(InternalCross.id)
        )
        .scalars()
        .all()
    )
    orders = (
        session.execute(
            select(ExecutionOrder)
            .where(ExecutionOrder.cycle_id == c.id)
            .order_by(ExecutionOrder.id)
        )
        .scalars()
        .all()
    )
    evs = (
        session.execute(
            select(SystemEvent).where(SystemEvent.cycle_id == c.id).order_by(SystemEvent.id)
        )
        .scalars()
        .all()
    )
    return {
        "cycle": ser.cycle(c),
        "signals": [
            ser.signal(r, sym.get(r.asset_id) if r.asset_id else None, codes.get(r.strategy_id))
            for r in sigs
        ],
        "internal_crosses": [
            ser.cross(
                r,
                sym.get(r.asset_id),
                codes.get(r.buyer_strategy_id),
                codes.get(r.seller_strategy_id),
            )
            for r in xs
        ],
        "executions": [ser.order(o, sym.get(o.asset_id), cfg.explorer_base_url) for o in orders],
        "events": [ser.event(e) for e in evs],
    }
