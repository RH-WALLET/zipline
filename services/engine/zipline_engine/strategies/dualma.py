"""DUALMA — classic dual moving average crossover, per asset.

Reminiscent of Zipline's ``dual_moving_average.py`` example (which traded one stock on a
100/300-day crossover); here it is applied per eligible asset with equal weights.
"""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    equal_weights,
)
from zipline_engine.strategies.indicators import last_valid, sma


class DualMovingAverageStrategy(Strategy):
    code = "DUALMA"
    name = "Dual Moving Average"
    description = "Holds each eligible asset whose 20-day average is above its 100-day average; otherwise holds cash for that name."
    default_params: dict[str, Any] = {"fast": 20, "slow": 100, "gross": 1.0}

    def min_history(self) -> int:
        return int(self.params["slow"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        close = self.closes(ctx, symbols)
        fast, slow = sma(close, int(p["fast"])), sma(close, int(p["slow"]))
        out: list[Signal] = []
        for s in symbols:
            f, sl = last_valid(fast, s), last_valid(slow, s)
            if f is None or sl is None:
                continue
            out.append(
                Signal(
                    "LONG" if f > sl else "FLAT",
                    s,
                    f / sl - 1.0,
                    {"sma_fast": round(f, 4), "sma_slow": round(sl, 4)},
                )
            )
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        longs = [s.symbol for s in signals if s.kind == "LONG" and s.symbol]
        return TargetResult(
            equal_weights(longs, float(self.params["gross"])),
            dict(ctx.state),
            [f"{len(longs)} crossovers long"],
        )

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least slow+5 sessions",
            "signal": f"SMA({p['fast']}) > SMA({p['slow']}) -> long; otherwise flat",
            "sizing": f"equal weight across long names, gross {p['gross']:.0%}",
            "rebalance": "daily after the US close",
            "lineage": "same rule family as Zipline's dual_moving_average example; parameters differ",
            "parameters": p,
        }
