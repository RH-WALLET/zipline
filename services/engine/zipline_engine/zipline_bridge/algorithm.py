"""Wrap an engine Strategy as a Zipline algorithm (initialize / scheduled rebalance).

The same ``Strategy.run`` that drives the live cycle drives the simulator: Zipline supplies
history through ``data.history`` and executes with ``order_target_percent``.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pandas as pd

from zipline_engine.core.calendar import session_index
from zipline_engine.marketdata.service import Panel
from zipline_engine.strategies.base import Strategy, StrategyContext


def panel_from_history(hist: pd.DataFrame, symbol_of: dict[Any, str]) -> Panel:
    """``data.history`` with several assets/fields returns a (dt, asset) MultiIndex frame."""

    def field(name: str) -> pd.DataFrame:
        f = hist[name].unstack(level=1)
        f.columns = [symbol_of[a] for a in f.columns]
        f.index = pd.DatetimeIndex(
            [
                pd.Timestamp(t).tz_localize(None).normalize()
                if pd.Timestamp(t).tzinfo
                else pd.Timestamp(t).normalize()
                for t in f.index
            ]
        )
        return f[sorted(f.columns)]

    return Panel(
        field("close"),
        field("high"),
        field("low"),
        field("open"),
        field("volume"),
        provider="zipline-bundle",
    )


def make_algorithm(
    strategy: Strategy, universe: list[str], lookback: int = 300, benchmark: str | None = "SPY"
) -> tuple[Callable[..., None], Callable[..., None] | None]:
    from zipline.api import (
        date_rules,
        order_target_percent,
        record,
        schedule_function,
        set_benchmark,
        set_commission,
        set_slippage,
        symbol,
        time_rules,
    )
    from zipline.finance import commission, slippage

    def initialize(context: Any) -> None:
        context.strategy = strategy
        context.symbols = sorted(universe)
        context.assets = [symbol(s) for s in context.symbols]
        context.symbol_of = {a: s for a, s in zip(context.assets, context.symbols, strict=True)}
        context.state = {"seed": 20200101} if strategy.code == "ZEROIQ" else {}
        context.benchmark = benchmark if benchmark in context.symbols else None
        if context.benchmark:
            set_benchmark(symbol(context.benchmark))
        set_commission(commission.PerDollar(cost=0.0))
        set_slippage(slippage.FixedBasisPointsSlippage(basis_points=5.0, volume_limit=1.0))
        schedule_function(rebalance, date_rules.every_day(), time_rules.market_close(minutes=1))

    def rebalance(context: Any, data: Any) -> None:
        hist = data.history(
            context.assets, ["open", "high", "low", "close", "volume"], lookback, "1d"
        )
        panel = panel_from_history(hist, context.symbol_of)
        today = data.current_dt.date()
        nav = float(context.portfolio.portfolio_value)
        current = {
            context.symbol_of[a]: Decimal(repr(float(p.amount * p.last_sale_price) / nav))
            if nav
            else Decimal(0)
            for a, p in context.portfolio.positions.items()
        }
        ctx = StrategyContext(
            session_date=today,
            universe=list(context.symbols),
            panel=panel,
            current_weights=current,
            state=dict(context.state),
            params=strategy.params,
            benchmark=context.benchmark,
            session_ordinal=session_index(today),
        )
        out = strategy.run(ctx)
        context.state = out.new_state
        for a in context.assets:
            if data.can_trade(a):
                order_target_percent(
                    a, float(out.target_weights.get(context.symbol_of[a], Decimal(0)))
                )
        record(
            n_positions=len(out.target_weights),
            gross=float(sum(out.target_weights.values(), Decimal(0))),
        )

    return initialize, None
