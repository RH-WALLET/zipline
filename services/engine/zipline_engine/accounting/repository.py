"""Load/save virtual books to the database."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.accounting.books import Book, FillResult, Valuation, book_from_row
from zipline_engine.core.money import ZERO, q_money
from zipline_engine.db.enums import FillKind
from zipline_engine.db.models import (
    Asset,
    PortfolioSnapshot,
    Strategy,
    StrategyAllocation,
    StrategyPosition,
    StrategyState,
    VirtualFill,
)


@dataclass
class LoadedBooks:
    books: dict[str, Book]
    strategies: dict[str, Strategy]
    states: dict[str, StrategyState]
    weights_pct: dict[str, Decimal]
    asset_by_symbol: dict[str, Asset]
    symbol_by_asset_id: dict[int, str]


class BookRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def asset_maps(self) -> tuple[dict[str, Asset], dict[int, str]]:
        assets = self.session.execute(select(Asset)).scalars().all()
        return {a.symbol: a for a in assets}, {a.id: a.symbol for a in assets}

    def load(self) -> LoadedBooks:
        asset_by_symbol, symbol_by_id = self.asset_maps()
        strategies = {
            s.code: s
            for s in self.session.execute(select(Strategy).order_by(Strategy.id)).scalars().all()
        }
        states = {
            st.strategy_id: st for st in self.session.execute(select(StrategyState)).scalars().all()
        }
        positions: dict[int, list[StrategyPosition]] = {}
        for p in self.session.execute(select(StrategyPosition)).scalars().all():
            positions.setdefault(p.strategy_id, []).append(p)
        weights = {}
        for a in (
            self.session.execute(
                select(StrategyAllocation).where(StrategyAllocation.active.is_(True))
            )
            .scalars()
            .all()
        ):
            weights[a.strategy_id] = Decimal(a.weight_pct)
        books: dict[str, Book] = {}
        state_by_code: dict[str, StrategyState] = {}
        weights_by_code: dict[str, Decimal] = {}
        for code, strat in strategies.items():
            st = states.get(strat.id)
            if st is None:
                st = StrategyState(strategy_id=strat.id)
                self.session.add(st)
                self.session.flush()
            books[code] = book_from_row(code, st, positions.get(strat.id, []), symbol_by_id)
            state_by_code[code] = st
            weights_by_code[code] = weights.get(strat.id, ZERO)
        return LoadedBooks(
            books, strategies, state_by_code, weights_by_code, asset_by_symbol, symbol_by_id
        )

    def save(
        self,
        book: Book,
        strategy: Strategy,
        state: StrategyState,
        valuation: Valuation | None,
        prices: dict[str, Decimal],
        asset_by_symbol: dict[str, Asset],
        cycle_id: int | None = None,
    ) -> None:
        state.virtual_cash = book.cash
        state.allocated_capital = book.allocated_capital
        state.realized_pnl = book.realized_pnl
        state.peak_nav = book.peak_nav
        state.max_drawdown_pct = book.max_drawdown_pct
        state.current_drawdown_pct = book.current_drawdown_pct
        state.cumulative_turnover = book.cumulative_turnover
        state.twr_index = book.twr_index
        state.fills_count = book.fills_count
        st = dict(book.state)
        st["_peak_index"] = str(book.peak_index)
        st["_pending_flow"] = str(book.pending_flow)
        state.state = st
        if valuation is not None:
            state.current_nav = valuation.nav
            state.unrealized_pnl = valuation.unrealized_pnl
        else:
            state.current_nav = q_money(book.nav(prices))
        if cycle_id is not None:
            state.last_cycle_id = cycle_id
        existing = {
            p.asset_id: p
            for p in self.session.execute(
                select(StrategyPosition).where(StrategyPosition.strategy_id == strategy.id)
            )
            .scalars()
            .all()
        }
        for sym, pos in book.positions.items():
            asset = asset_by_symbol.get(sym)
            if asset is None:
                continue
            row = existing.pop(asset.id, None)
            if row is None:
                if pos.quantity <= 0:
                    continue
                row = StrategyPosition(strategy_id=strategy.id, asset_id=asset.id)
                self.session.add(row)
            px = prices.get(sym, pos.avg_cost)
            row.quantity = pos.quantity
            row.cost_basis = pos.cost_basis
            row.last_price = px
            row.market_value = q_money(pos.market_value(px))
            row.unrealized_pnl = q_money(pos.unrealized_pnl(px))
        for row in existing.values():  # positions no longer in the book
            row.quantity = ZERO
            row.cost_basis = ZERO
            row.market_value = ZERO
            row.unrealized_pnl = ZERO
        self.session.flush()

    def record_fill(
        self,
        *,
        strategy: Strategy,
        asset: Asset,
        fill: FillResult,
        kind: FillKind,
        cycle_id: int | None,
        internal_cross_id: int | None = None,
        execution_order_id: int | None = None,
    ) -> VirtualFill:
        vf = VirtualFill(
            cycle_id=cycle_id,
            strategy_id=strategy.id,
            asset_id=asset.id,
            side=str(fill.side),
            kind=str(kind),
            quantity=fill.quantity,
            price=fill.price,
            notional=q_money(fill.notional),
            realized_pnl=q_money(fill.realized_pnl),
            internal_cross_id=internal_cross_id,
            execution_order_id=execution_order_id,
        )
        self.session.add(vf)
        return vf

    def snapshot(
        self,
        book: Book,
        strategy: Strategy,
        valuation: Valuation,
        prices: dict[str, Decimal],
        taken_at: datetime | None = None,
    ) -> PortfolioSnapshot:
        snap = PortfolioSnapshot(
            strategy_id=strategy.id,
            taken_at=taken_at or datetime.now(UTC),
            nav=valuation.nav,
            cash=valuation.cash,
            positions_value=valuation.positions_value,
            allocated_capital=q_money(book.allocated_capital),
            realized_pnl=valuation.realized_pnl,
            unrealized_pnl=valuation.unrealized_pnl,
            drawdown_pct=valuation.drawdown_pct.quantize(Decimal("1e-6")),
            twr_index=valuation.twr_index,
            positions=book.snapshot_positions(prices),
        )
        self.session.add(snap)
        return snap

    @staticmethod
    def sum_positions(books: dict[str, Book]) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for b in books.values():
            for s, p in b.positions.items():
                if p.quantity > 0:
                    out[s] = out.get(s, ZERO) + p.quantity
        return dict(sorted(out.items()))

    @staticmethod
    def sum_cash(books: dict[str, Book]) -> Decimal:
        return sum((b.cash for b in books.values()), ZERO)

    @staticmethod
    def jsonable_weights(w: dict[str, Any]) -> dict[str, str]:
        return {k: str(v) for k, v in w.items()}
