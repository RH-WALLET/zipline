"""Reconciliation: sum of sleeve books vs the real treasury.

Identity checked after every execution and on a schedule:

    Σ_sleeves position(symbol)  ==  treasury position(symbol)        for every symbol
    Σ_sleeves cash              <=  treasury cash                     (the remainder is the reserve/buffer)

Tolerance (documented, configurable): RECONCILIATION_TOLERANCE_BPS of NAV per line, which
absorbs 18-decimal rounding and execution rounding. Anything beyond it is a break; a break
pauses live trading automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from zipline_engine.accounting.books import Book
from zipline_engine.accounting.repository import BookRepository
from zipline_engine.config import Settings
from zipline_engine.core.money import ZERO, q_money
from zipline_engine.core.system import get_state, pause
from zipline_engine.db.enums import EventLevel, EventType, ReconciliationStatus
from zipline_engine.db.models import ReconciliationEvent
from zipline_engine.events.bus import EventBus
from zipline_engine.treasury.backends import TreasuryBalances

log = logging.getLogger(__name__)

QTY_TOL = Decimal("1e-9")


@dataclass
class ReconciliationResult:
    status: ReconciliationStatus
    nav: Decimal
    tolerance_bps: int
    position_breaks: list[dict[str, Any]] = field(default_factory=list)
    cash_break: Decimal = ZERO
    buffer_cash: Decimal = ZERO
    reserve_target: Decimal = ZERO
    max_break_bps: Decimal = ZERO
    lines: list[dict[str, Any]] = field(default_factory=list)


def reconcile(
    books: dict[str, Book],
    treasury: TreasuryBalances,
    token_prices: dict[str, Decimal],
    *,
    nav: Decimal,
    tolerance_bps: int,
    reserve_target: Decimal,
) -> ReconciliationResult:
    """Pure comparison. ``token_prices`` are USD per raw token (for bps-of-NAV tolerance)."""
    book_positions = BookRepository.sum_positions(books)
    book_cash = BookRepository.sum_cash(books)
    result = ReconciliationResult(
        ReconciliationStatus.OK, nav, tolerance_bps, reserve_target=reserve_target
    )
    tol_value = nav * Decimal(tolerance_bps) / Decimal(10_000) if nav > 0 else ZERO
    symbols = sorted(set(book_positions) | set(treasury.positions))
    for sym in symbols:
        b = book_positions.get(sym, ZERO)
        t = treasury.positions.get(sym, ZERO)
        diff = b - t
        px = token_prices.get(sym, ZERO)
        diff_value = abs(diff) * px
        diff_bps = (diff_value / nav * Decimal(10_000)) if nav > 0 else ZERO
        line = {
            "symbol": sym,
            "books": str(b),
            "treasury": str(t),
            "diff": str(diff),
            "diff_value": str(q_money(diff_value)),
            "diff_bps": str(diff_bps.quantize(Decimal("0.0001"))),
        }
        result.lines.append(line)
        is_break = abs(diff) > QTY_TOL and (px == 0 or diff_value > tol_value)
        if is_break:
            result.position_breaks.append(line)
        if diff_bps > result.max_break_bps:
            result.max_break_bps = diff_bps
    buffer = treasury.cash - book_cash
    result.buffer_cash = q_money(buffer)
    if buffer < -tol_value:
        result.cash_break = q_money(buffer)
    if result.position_breaks or result.cash_break != 0:
        result.status = ReconciliationStatus.FAILED
    return result


class ReconciliationService:
    def __init__(self, session: Session, settings: Settings, events: EventBus) -> None:
        self.session = session
        self.settings = settings
        self.events = events

    def run(
        self,
        books: dict[str, Book],
        treasury: TreasuryBalances,
        token_prices: dict[str, Decimal],
        *,
        nav: Decimal,
        reserve_target: Decimal,
        trigger: str,
    ) -> ReconciliationEvent:
        res = reconcile(
            books,
            treasury,
            token_prices,
            nav=nav,
            tolerance_bps=self.settings.reconciliation_tolerance_bps,
            reserve_target=reserve_target,
        )
        failed = res.status == ReconciliationStatus.FAILED
        details = {
            "trigger": trigger,
            "mode": treasury.mode,
            "source": treasury.source,
            "nav": str(nav),
            "treasury_cash": str(q_money(treasury.cash)),
            "sleeve_cash": str(q_money(BookRepository.sum_cash(books))),
            "buffer_cash": str(res.buffer_cash),
            "reserve_target": str(reserve_target),
            "lines": res.lines,
            "block_number": treasury.block_number,
        }
        ev = ReconciliationEvent(
            run_at=datetime.now(UTC),
            mode=treasury.mode,
            status=str(res.status),
            tolerance_bps=res.tolerance_bps,
            max_break_bps=res.max_break_bps.quantize(Decimal("0.0001")),
            cash_break=res.cash_break,
            position_breaks=res.position_breaks,
            details=details,
            triggered_pause=False,
        )
        self.session.add(ev)
        st = get_state(self.session)
        st.last_reconciliation_status = str(res.status)
        st.last_reconciliation_at = ev.run_at
        self.session.flush()
        if failed:
            msg = f"reconciliation FAILED ({trigger}): {len(res.position_breaks)} position break(s), cash break {res.cash_break}"
            self.events.emit(
                EventType.RECONCILIATION_FAILED,
                msg,
                level=EventLevel.ERROR,
                payload={"breaks": res.position_breaks, "cash_break": str(res.cash_break)},
            )
            pause(self.session, self.events, "RECONCILIATION_FAILED: " + msg)
            ev.triggered_pause = True
        else:
            self.events.emit(
                EventType.RECONCILIATION_OK,
                f"reconciliation OK ({trigger}): {len(res.lines)} lines, max deviation {res.max_break_bps:.2f} bps, buffer cash {res.buffer_cash}",
                payload={
                    "lines": len(res.lines),
                    "max_break_bps": str(res.max_break_bps),
                    "buffer_cash": str(res.buffer_cash),
                },
            )
        self.session.flush()
        return ev
