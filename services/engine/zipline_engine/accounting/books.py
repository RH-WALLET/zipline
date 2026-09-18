"""Virtual strategy books (sleeves).

A book is pure in-memory accounting for one strategy: cash, raw-token positions with average
cost, realized PnL, time-weighted return index and drawdown. Persistence is done elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from zipline_engine.core.money import ZERO, D, q_money, q_qty, safe_div
from zipline_engine.db.enums import Side


@dataclass
class Position:
    symbol: str
    quantity: Decimal = ZERO  # raw tokens
    cost_basis: Decimal = ZERO  # USD paid for the current quantity (average-cost method)

    @property
    def avg_cost(self) -> Decimal:
        return safe_div(self.cost_basis, self.quantity)

    def market_value(self, price: Decimal) -> Decimal:
        return self.quantity * price

    def unrealized_pnl(self, price: Decimal) -> Decimal:
        return self.market_value(price) - self.cost_basis


@dataclass
class FillResult:
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    notional: Decimal
    realized_pnl: Decimal


@dataclass
class Valuation:
    nav: Decimal
    cash: Decimal
    positions_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    drawdown_pct: Decimal
    twr_index: Decimal
    period_return: Decimal
    weights: dict[str, Decimal]
    missing_prices: list[str]


@dataclass
class Book:
    code: str
    cash: Decimal = ZERO
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: Decimal = ZERO
    allocated_capital: Decimal = ZERO
    peak_nav: Decimal = ZERO
    max_drawdown_pct: Decimal = ZERO
    current_drawdown_pct: Decimal = ZERO
    cumulative_turnover: Decimal = ZERO
    twr_index: Decimal = Decimal(1)
    peak_index: Decimal = Decimal(1)
    last_nav: Decimal = ZERO
    pending_flow: Decimal = ZERO
    fills_count: int = 0
    state: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- valuation
    def positions_value(self, prices: dict[str, Decimal]) -> Decimal:
        total = ZERO
        for sym, pos in self.positions.items():
            if pos.quantity == 0:
                continue
            px = prices.get(sym)
            if px is None:
                px = pos.avg_cost  # no price: carry at cost, flagged by ``mark``
            total += pos.market_value(px)
        return total

    def nav(self, prices: dict[str, Decimal]) -> Decimal:
        return self.cash + self.positions_value(prices)

    def weights(self, prices: dict[str, Decimal]) -> dict[str, Decimal]:
        nav = self.nav(prices)
        if nav <= 0:
            return {}
        out: dict[str, Decimal] = {}
        for sym, pos in sorted(self.positions.items()):
            if pos.quantity > 0:
                out[sym] = pos.market_value(prices.get(sym, pos.avg_cost)) / nav
        return out

    def held_symbols(self) -> list[str]:
        return sorted(s for s, p in self.positions.items() if p.quantity > 0)

    # ------------------------------------------------------------- flows
    def add_capital(self, amount: Decimal) -> None:
        if amount < 0:
            raise ValueError("use remove_capital for withdrawals")
        self.cash += amount
        self.allocated_capital += amount
        self.pending_flow += amount

    def remove_capital(self, amount: Decimal) -> Decimal:
        """Withdraw cash from the sleeve. Returns the amount actually removed (bounded by cash)."""
        if amount < 0:
            raise ValueError("amount must be positive")
        taken = min(amount, self.cash)
        self.cash -= taken
        self.allocated_capital -= taken
        self.pending_flow -= taken
        return taken

    # ------------------------------------------------------------- fills
    def apply_fill(
        self,
        symbol: str,
        side: Side,
        quantity: Decimal,
        price: Decimal,
        *,
        allow_overdraft: bool = False,
    ) -> FillResult:
        if quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if price <= 0:
            raise ValueError("fill price must be positive")
        quantity = q_qty(quantity)
        notional = quantity * price
        pos = self.positions.setdefault(symbol, Position(symbol))
        realized = ZERO
        if side == Side.BUY:
            if notional > self.cash + Decimal("1e-9") and not allow_overdraft:
                raise InsufficientCashError(
                    f"{self.code}: buy {symbol} {notional:.6f} exceeds sleeve cash {self.cash:.6f}"
                )
            self.cash -= notional
            pos.quantity += quantity
            pos.cost_basis += notional
        else:
            if quantity > pos.quantity + Decimal("1e-12"):
                raise InsufficientPositionError(
                    f"{self.code}: sell {quantity} {symbol} exceeds position {pos.quantity}"
                )
            quantity = min(quantity, pos.quantity)
            avg = pos.avg_cost
            cost_out = avg * quantity
            realized = notional - cost_out
            pos.quantity -= quantity
            pos.cost_basis -= cost_out
            if pos.quantity <= Decimal("1e-15"):
                pos.quantity = ZERO
                pos.cost_basis = ZERO
            self.cash += notional
            self.realized_pnl += realized
        self.cumulative_turnover += notional
        self.fills_count += 1
        return FillResult(symbol, side, quantity, price, notional, realized)

    # ------------------------------------------------------------- marking
    def mark(self, prices: dict[str, Decimal]) -> Valuation:
        missing = [s for s, p in self.positions.items() if p.quantity > 0 and s not in prices]
        pv = self.positions_value(prices)
        nav = self.cash + pv
        unrealized = sum(
            (
                p.unrealized_pnl(prices.get(s, p.avg_cost))
                for s, p in self.positions.items()
                if p.quantity > 0
            ),
            ZERO,
        )
        period_return = ZERO
        if self.last_nav > 0:
            base = (
                self.last_nav + self.pending_flow
            )  # flows are assumed to arrive at the start of the period
            if base > 0:
                period_return = nav / base - 1
        self.twr_index = self.twr_index * (1 + period_return)
        self.pending_flow = ZERO
        self.last_nav = nav
        if self.twr_index > self.peak_index:
            self.peak_index = self.twr_index
        if nav > self.peak_nav:
            self.peak_nav = nav
        dd = (safe_div(self.twr_index, self.peak_index) - 1) * 100 if self.peak_index > 0 else ZERO
        self.current_drawdown_pct = dd
        if dd < self.max_drawdown_pct:
            self.max_drawdown_pct = dd
        return Valuation(
            nav=q_money(nav),
            cash=q_money(self.cash),
            positions_value=q_money(pv),
            unrealized_pnl=q_money(unrealized),
            realized_pnl=q_money(self.realized_pnl),
            drawdown_pct=dd,
            twr_index=self.twr_index,
            period_return=period_return,
            weights=self.weights(prices),
            missing_prices=missing,
        )

    @property
    def total_return_pct(self) -> Decimal:
        return (self.twr_index - 1) * 100

    def snapshot_positions(self, prices: dict[str, Decimal]) -> dict[str, dict[str, str]]:
        return {
            s: {
                "quantity": str(p.quantity),
                "cost_basis": str(q_money(p.cost_basis)),
                "avg_cost": str(q_money(p.avg_cost)),
                "price": str(prices.get(s, p.avg_cost)),
                "market_value": str(q_money(p.market_value(prices.get(s, p.avg_cost)))),
            }
            for s, p in sorted(self.positions.items())
            if p.quantity > 0
        }


class InsufficientCashError(ValueError):
    pass


class InsufficientPositionError(ValueError):
    pass


def book_from_row(
    code: str, state_row: Any, position_rows: list[Any], symbol_by_asset_id: dict[int, str]
) -> Book:
    """Rehydrate a Book from ORM rows (StrategyState + StrategyPosition)."""
    book = Book(
        code=code,
        cash=D(state_row.virtual_cash),
        realized_pnl=D(state_row.realized_pnl),
        allocated_capital=D(state_row.allocated_capital),
        peak_nav=D(state_row.peak_nav),
        max_drawdown_pct=D(state_row.max_drawdown_pct),
        current_drawdown_pct=D(state_row.current_drawdown_pct),
        cumulative_turnover=D(state_row.cumulative_turnover),
        twr_index=D(state_row.twr_index) if state_row.twr_index else Decimal(1),
        last_nav=D(state_row.current_nav),
        fills_count=int(state_row.fills_count or 0),
        state=dict(state_row.state or {}),
    )
    book.peak_index = D(book.state.get("_peak_index", book.twr_index))
    book.pending_flow = D(book.state.get("_pending_flow", 0))
    for row in position_rows:
        sym = symbol_by_asset_id.get(row.asset_id)
        if sym is None or D(row.quantity) <= 0:
            continue
        book.positions[sym] = Position(sym, D(row.quantity), D(row.cost_basis))
    return book
