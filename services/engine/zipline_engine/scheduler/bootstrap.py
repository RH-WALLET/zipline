"""Idempotent database bootstrap: strategies, versions, allocations, sleeves, system state, funding."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from zipline_engine.accounting.allocation import check_max_strategy_allocation
from zipline_engine.core.money import D
from zipline_engine.core.system import get_state
from zipline_engine.db.enums import EventLevel, EventType, FundingKind
from zipline_engine.db.models import Strategy, StrategyAllocation, StrategyState, StrategyVersion
from zipline_engine.runtime import Runtime
from zipline_engine.strategies.base import Strategy as StrategyImpl
from zipline_engine.strategies.registry import STRATEGY_CLASSES

log = logging.getLogger(__name__)


def ensure_strategy_rows(rt: Runtime) -> dict[str, Strategy]:
    session = rt.session
    out: dict[str, Strategy] = {}
    n = len(STRATEGY_CLASSES)
    equal = (Decimal(100) / n).quantize(Decimal("0.000001"))
    for cls in STRATEGY_CLASSES:
        row = session.execute(
            select(Strategy).where(Strategy.code == cls.code)
        ).scalar_one_or_none()
        if row is None:
            row = Strategy(
                code=cls.code,
                name=cls.name,
                description=cls.description,
                enabled=True,
                status="ACTIVE",
            )
            session.add(row)
            session.flush()
        impl = load_strategy_impl(rt, row)
        ensure_version(rt, row, impl)
        st = session.execute(
            select(StrategyState).where(StrategyState.strategy_id == row.id)
        ).scalar_one_or_none()
        if st is None:
            st = StrategyState(strategy_id=row.id, state={})
            session.add(st)
            session.flush()
        if cls.code == "ZEROIQ" and "seed" not in (st.state or {}):
            state = dict(st.state or {})
            state["seed"] = secrets.randbits(63)
            st.state = state
            session.flush()
            rt.events.emit(
                EventType.CONFIG_WARNING,
                f"ZEROIQ seed created and persisted: {state['seed']}",
                payload={"seed": state["seed"]},
            )
        alloc = session.execute(
            select(StrategyAllocation).where(
                StrategyAllocation.strategy_id == row.id, StrategyAllocation.active.is_(True)
            )
        ).scalar_one_or_none()
        if alloc is None:
            session.add(
                StrategyAllocation(
                    strategy_id=row.id,
                    weight_pct=equal,
                    policy="EQUAL_WEIGHT",
                    active=True,
                    note="bootstrap equal weight",
                )
            )
        out[cls.code] = row
    session.flush()
    weights = {}
    for a in (
        session.execute(select(StrategyAllocation).where(StrategyAllocation.active.is_(True)))
        .scalars()
        .all()
    ):
        code = next(c for c, s in out.items() if s.id == a.strategy_id)
        weights[code] = D(a.weight_pct) / 100
    for problem in check_max_strategy_allocation(
        weights, rt.settings.max_strategy_allocation_pct, rt.settings.cash_reserve_pct
    ):
        rt.events.emit(EventType.CONFIG_WARNING, problem, level=EventLevel.WARN)
    return out


def load_strategy_impl(rt: Runtime, row: Strategy) -> StrategyImpl:
    """Build the strategy with the params of its most recent version (operator-editable)."""
    from zipline_engine.strategies.registry import build_strategy

    latest = rt.session.execute(
        select(StrategyVersion)
        .where(StrategyVersion.strategy_id == row.id)
        .order_by(StrategyVersion.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return build_strategy(row.code, latest.params if latest else None)


def ensure_version(rt: Runtime, row: Strategy, impl: StrategyImpl) -> StrategyVersion:
    h = impl.get_version_hash()
    existing = rt.session.execute(
        select(StrategyVersion).where(
            StrategyVersion.strategy_id == row.id, StrategyVersion.version_hash == h
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = StrategyVersion(
            strategy_id=row.id,
            version_hash=h,
            source_hash=impl.source_hash(),
            params=impl.params,
            rules=impl.describe_rules(),
        )
        rt.session.add(existing)
    if row.current_version_hash != h:
        row.current_version_hash = h
    rt.session.flush()
    return existing


def bootstrap(rt: Runtime) -> None:
    """Create everything a fresh database needs. Safe to run repeatedly."""
    session = rt.session
    settings = rt.settings
    st = get_state(session)
    first_time = st.bootstrapped_at is None
    ensure_strategy_rows(rt)
    if first_time:
        rt.events.emit(
            EventType.SYSTEM_STARTED,
            f"bootstrap: mode={settings.treasury_mode} live_trading={settings.live_trading} chain={settings.chain_id}",
            payload={
                "mode": settings.treasury_mode,
                "live_trading": settings.live_trading,
                "chain_id": settings.chain_id,
            },
        )
    sim = rt.simulated
    if sim is not None:
        if sim.is_empty():
            sim.deposit_cash(settings.demo_initial_cash)
            sim.set_gas(settings.demo_initial_gas_eth)
            rt.funding.record_funding(
                FundingKind.DEMO_SEED,
                settings.demo_initial_cash,
                note="DEMO MODE seed capital (simulated treasury)",
            )
    else:
        # onchain: the opening balance is the base capital
        if first_time:
            assets = rt.universe.all_assets()
            balances = rt.treasury.read_balances(assets)
            if balances.cash > 0:
                rt.funding.record_funding(
                    FundingKind.BASE_CAPITAL,
                    balances.cash,
                    block_number=balances.block_number,
                    note="opening cash balance at bootstrap",
                )
            state = get_state(session)
            meta = dict(state.meta or {})
            meta["last_funding_block"] = balances.block_number
            state.meta = meta
    st = get_state(session)
    if st.bootstrapped_at is None:
        st.bootstrapped_at = datetime.now(UTC)
    session.flush()
