"""Operator endpoints. Bearer ADMIN_TOKEN required. Nothing here is exposed to the public UI."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.api import serializers as ser
from zipline_engine.api.deps import db, require_admin, settings
from zipline_engine.config import Settings
from zipline_engine.core.money import D
from zipline_engine.core.system import get_state, pause, resume
from zipline_engine.db.enums import EventType, FundingKind
from zipline_engine.db.models import Strategy
from zipline_engine.events.bus import EventBus
from zipline_engine.runtime import build_runtime
from zipline_engine.scheduler.cycle import CycleError, run_cycle, run_reconciliation, run_valuation

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


class Note(BaseModel):
    note: str = Field(default="operator", max_length=200)


class Deposit(BaseModel):
    amount: Decimal = Field(gt=0)
    note: str = Field(default="simulated deposit", max_length=200)


class Withdrawal(BaseModel):
    amount: Decimal = Field(gt=0)
    to_address: str | None = None
    tx_hash: str | None = None
    note: str = Field(default="operator withdrawal", max_length=200)


@router.post("/pause")
def admin_pause(body: Note, session: Session = Depends(db)) -> dict[str, Any]:
    st = pause(session, EventBus(session), f"operator: {body.note}")
    return {"paused": st.paused, "reason": st.pause_reason}


@router.post("/resume")
def admin_resume(body: Note, session: Session = Depends(db)) -> dict[str, Any]:
    st = resume(session, EventBus(session), body.note)
    return {"paused": st.paused}


@router.post("/run-cycle")
def admin_run_cycle(
    force: bool = False, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    rt = build_runtime(session, cfg)
    try:
        cycle = run_cycle(rt, force=force)
    except CycleError as e:
        raise HTTPException(409, str(e)) from e
    return ser.cycle(cycle)


@router.post("/reconcile")
def admin_reconcile(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    rt = build_runtime(session, cfg)
    ev = run_reconciliation(rt, trigger="operator")
    return ser.reconciliation(ev)


@router.post("/revalue")
def admin_revalue(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    rt = build_runtime(session, cfg)
    v = run_valuation(rt, refresh_universe=True)
    return {"nav": str(v.nav), "cash": str(v.cash), "positions_value": str(v.positions_value)}


def _set_enabled(session: Session, code: str, enabled: bool, note: str) -> dict[str, Any]:
    s = session.execute(select(Strategy).where(Strategy.code == code.upper())).scalar_one_or_none()
    if s is None:
        raise HTTPException(404, f"unknown strategy {code}")
    events = EventBus(session)
    previous = s.status
    s.enabled = enabled
    if enabled:
        s.status = "ACTIVE"
        s.status_reason = f"re-enabled by operator: {note}"
    else:
        s.status = "DISABLED"
        s.status_reason = f"disabled by operator: {note}"
    session.flush()
    events.emit(
        EventType.STRATEGY_STATUS_CHANGED,
        f"{s.code}: {previous} -> {s.status} ({s.status_reason})",
        payload={"strategy": s.code, "from": previous, "to": s.status},
    )
    return ser.row(s)


@router.post("/strategy/{code}/enable")
def admin_enable(code: str, body: Note, session: Session = Depends(db)) -> dict[str, Any]:
    return _set_enabled(session, code, True, body.note)


@router.post("/strategy/{code}/disable")
def admin_disable(code: str, body: Note, session: Session = Depends(db)) -> dict[str, Any]:
    return _set_enabled(session, code, False, body.note)


@router.post("/demo/deposit")
def admin_demo_deposit(
    body: Deposit, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    """DEMO MODE ONLY: credit the simulated treasury and record a contribution."""
    rt = build_runtime(session, cfg)
    if rt.simulated is None:
        raise HTTPException(
            400,
            "demo deposits only exist for TREASURY_MODE=simulated; fund the real wallet instead",
        )
    rt.simulated.deposit_cash(D(body.amount))
    ev = rt.funding.record_funding(
        FundingKind.CONTRIBUTION, D(body.amount), note=f"SIMULATED: {body.note}"
    )
    run_valuation(rt)
    return ser.funding(ev, cfg.explorer_base_url)


@router.post("/withdraw")
def admin_withdraw(
    body: Withdrawal, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    """Record an operator withdrawal and deallocate sleeve cash. Onchain transfer is done via the CLI."""
    from zipline_engine.scheduler.withdraw import record_withdrawal

    rt = build_runtime(session, cfg)
    ev = record_withdrawal(
        rt,
        D(body.amount),
        to_address=body.to_address,
        tx_hash=body.tx_hash,
        note=body.note,
        broadcast=False,
    )
    return ser.withdrawal(ev, cfg.explorer_base_url)


@router.get("/state")
def admin_state(session: Session = Depends(db)) -> dict[str, Any]:
    return ser.row(get_state(session))
