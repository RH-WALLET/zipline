"""SystemState helpers: global pause, failure counter, daily turnover ledger."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.core.money import ZERO, D
from zipline_engine.db.enums import EventLevel, EventType
from zipline_engine.db.models import SystemState
from zipline_engine.events.bus import EventBus


def get_state(session: Session) -> SystemState:
    st = session.execute(select(SystemState).where(SystemState.id == 1)).scalar_one_or_none()
    if st is None:
        st = SystemState(id=1)
        session.add(st)
        session.flush()
    return st


def pause(session: Session, events: EventBus, reason: str) -> SystemState:
    st = get_state(session)
    if not st.paused:
        st.paused = True
        st.pause_reason = reason[:256]
        st.paused_at = datetime.now(UTC)
        session.flush()
        events.emit(
            EventType.SYSTEM_PAUSED,
            f"system paused: {reason}",
            level=EventLevel.ERROR,
            payload={"reason": reason},
        )
    return st


def resume(session: Session, events: EventBus, note: str = "operator") -> SystemState:
    st = get_state(session)
    st.paused = False
    st.pause_reason = None
    st.paused_at = None
    st.consecutive_failed_txs = 0
    session.flush()
    events.emit(EventType.SYSTEM_RESUMED, f"system resumed ({note})", payload={"by": note})
    return st


def record_failed_tx(session: Session, events: EventBus, max_failures: int) -> bool:
    """Increment the consecutive-failure counter; pause when the limit is hit. Returns paused?"""
    st = get_state(session)
    st.consecutive_failed_txs = int(st.consecutive_failed_txs or 0) + 1
    session.flush()
    if st.consecutive_failed_txs >= max_failures:
        pause(
            session,
            events,
            f"{st.consecutive_failed_txs} consecutive failed executions (MAX_FAILED_TXS_BEFORE_PAUSE={max_failures})",
        )
        return True
    return False


def reset_failures(session: Session) -> None:
    st = get_state(session)
    st.consecutive_failed_txs = 0
    session.flush()


def turnover_today(session: Session, day: date) -> Decimal:
    st = get_state(session)
    if st.turnover_date != day:
        return ZERO
    return D(st.turnover_notional)


def add_turnover(session: Session, day: date, notional: Decimal) -> Decimal:
    st = get_state(session)
    if st.turnover_date != day:
        st.turnover_date = day
        st.turnover_notional = ZERO
    st.turnover_notional = D(st.turnover_notional) + notional
    session.flush()
    return D(st.turnover_notional)
