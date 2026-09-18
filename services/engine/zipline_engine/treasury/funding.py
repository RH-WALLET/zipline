"""Funding events, withdrawals and capital allocation into sleeves.

Contributions are never PnL. New deployable capital is split across ACTIVE sleeves by the
active allocation policy; the cash reserve share stays at treasury level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.accounting.allocation import (
    POLICIES,
    AllocationPolicy,
    SleeveInfo,
    distribute,
)
from zipline_engine.accounting.books import Book
from zipline_engine.config import Settings
from zipline_engine.core.money import ZERO, D, q_money
from zipline_engine.db.enums import EventLevel, EventType, FundingKind, StrategyStatus
from zipline_engine.db.models import FundingEvent, Strategy, WithdrawalEvent
from zipline_engine.events.bus import EventBus

log = logging.getLogger(__name__)


@dataclass
class AllocationOutcome:
    total: Decimal
    to_sleeves: dict[str, Decimal]
    to_reserve: Decimal


class CapitalAllocator:
    def __init__(self, settings: Settings, policy: AllocationPolicy | None = None) -> None:
        self.settings = settings
        self.policy = policy or POLICIES["MANUAL"]

    def sleeve_infos(
        self,
        strategies: dict[str, Strategy],
        books: dict[str, Book],
        weights_pct: dict[str, Decimal],
    ) -> list[SleeveInfo]:
        return [
            SleeveInfo(
                code=code,
                active=(s.status == StrategyStatus.ACTIVE or s.status == StrategyStatus.WATCH)
                and s.enabled,
                configured_weight_pct=weights_pct.get(code, ZERO),
                twr_index=books[code].twr_index if code in books else Decimal(1),
                drawdown_pct=books[code].current_drawdown_pct if code in books else ZERO,
            )
            for code, s in strategies.items()
        ]

    def allocate(
        self,
        amount: Decimal,
        strategies: dict[str, Strategy],
        books: dict[str, Book],
        weights_pct: dict[str, Decimal],
    ) -> AllocationOutcome:
        """Split a cash inflow: reserve share stays at treasury, the rest goes to active sleeves."""
        if amount <= 0:
            return AllocationOutcome(ZERO, {}, ZERO)
        reserve = q_money(amount * self.settings.cash_reserve_pct / 100)
        deployable = q_money(amount) - reserve
        weights = self.policy.target_weights(self.sleeve_infos(strategies, books, weights_pct))
        parts = distribute(deployable, weights)
        for code, part in parts.items():
            books[code].add_capital(part)
        unallocated = deployable - sum(parts.values(), ZERO)
        return AllocationOutcome(q_money(amount), parts, reserve + unallocated)

    def deallocate(
        self, amount: Decimal, books: dict[str, Book], buffer_cash: Decimal
    ) -> dict[str, Decimal]:
        """Fund a withdrawal: first from treasury buffer cash, then pro-rata from sleeve cash."""
        taken: dict[str, Decimal] = {}
        remaining = amount - max(min(buffer_cash, amount), ZERO)
        if remaining <= 0:
            return taken
        cash_weights = {c: b.cash for c, b in books.items() if b.cash > 0}
        total_cash = sum(cash_weights.values(), ZERO)
        if total_cash < remaining:
            raise ValueError(
                f"withdrawal needs {remaining} from sleeves but only {total_cash} cash is available; liquidate first"
            )
        for code, part in distribute(remaining, cash_weights).items():
            taken[code] = books[code].remove_capital(part)
        return taken


class FundingService:
    def __init__(self, session: Session, settings: Settings, events: EventBus) -> None:
        self.session = session
        self.settings = settings
        self.events = events

    def record_funding(
        self,
        kind: FundingKind,
        amount: Decimal,
        *,
        tx_hash: str | None = None,
        from_address: str | None = None,
        block_number: int | None = None,
        note: str | None = None,
    ) -> FundingEvent:
        if amount <= 0:
            raise ValueError("funding amount must be positive")
        ev = FundingEvent(
            kind=str(kind),
            amount=q_money(amount),
            asset_symbol=self.settings.cash_token_symbol,
            tx_hash=tx_hash,
            from_address=from_address,
            block_number=block_number,
            detected_at=datetime.now(UTC),
            note=note,
        )
        self.session.add(ev)
        self.session.flush()
        self.events.emit(
            EventType.FUNDING_RECEIVED,
            f"{kind} {q_money(amount)} {self.settings.cash_token_symbol}"
            + (f" tx {tx_hash}" if tx_hash else ""),
            payload={
                "kind": str(kind),
                "amount": str(q_money(amount)),
                "tx_hash": tx_hash,
                "from": from_address,
                "block": block_number,
            },
        )
        return ev

    def mark_allocated(self, ev: FundingEvent, outcome: AllocationOutcome) -> None:
        ev.allocated = True
        ev.allocation = {
            "to_sleeves": {k: str(v) for k, v in outcome.to_sleeves.items()},
            "to_reserve": str(outcome.to_reserve),
        }
        self.session.flush()

    def unallocated_events(self) -> list[FundingEvent]:
        return list(
            self.session.execute(
                select(FundingEvent)
                .where(FundingEvent.allocated.is_(False))
                .order_by(FundingEvent.id)
            )
            .scalars()
            .all()
        )

    def known_tx_hashes(self) -> set[str]:
        return {
            h
            for (h,) in self.session.execute(
                select(FundingEvent.tx_hash).where(FundingEvent.tx_hash.is_not(None))
            ).all()
        }

    def record_withdrawal(
        self,
        amount: Decimal,
        to_address: str | None,
        tx_hash: str | None,
        deallocation: dict[str, Decimal],
        note: str | None = None,
        status: str = "RECORDED",
    ) -> WithdrawalEvent:
        ev = WithdrawalEvent(
            amount=q_money(amount),
            asset_symbol=self.settings.cash_token_symbol,
            to_address=to_address,
            tx_hash=tx_hash,
            status=status,
            deallocation={k: str(v) for k, v in deallocation.items()},
            note=note,
        )
        self.session.add(ev)
        self.session.flush()
        self.events.emit(
            EventType.WITHDRAWAL_RECORDED,
            f"withdrawal {q_money(amount)} {self.settings.cash_token_symbol}"
            + (f" to {to_address}" if to_address else ""),
            level=EventLevel.WARN,
            payload={
                "amount": str(q_money(amount)),
                "to": to_address,
                "tx_hash": tx_hash,
                "deallocation": ev.deallocation,
            },
        )
        return ev


def d(x: object) -> Decimal:
    return D(x)
