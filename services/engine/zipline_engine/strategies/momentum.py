"""MOMENTUM — cross-sectional 12-1 momentum."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    equal_weights,
)
from zipline_engine.strategies.indicators import last_valid


class MomentumStrategy(Strategy):
    code = "MOMENTUM"
    name = "Momentum"
    description = "Ranks eligible assets by 12-month return excluding the most recent month; holds the top names equal-weighted."
    default_params: dict[str, Any] = {
        "lookback": 252,
        "skip": 21,
        "top_n": 4,
        "min_return": 0.0,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["lookback"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        close = self.closes(ctx, symbols)
        lb, skip = int(p["lookback"]), int(p["skip"])
        score = close.shift(skip) / close.shift(lb) - 1.0
        out: list[Signal] = []
        for s in symbols:
            v = last_valid(score, s)
            if v is None:
                continue
            out.append(Signal("MOMENTUM_SCORE", s, v, {"return_12_1": round(v, 6)}))
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        scored = [
            s
            for s in signals
            if s.kind == "MOMENTUM_SCORE" and s.symbol and (s.value or 0) > float(p["min_return"])
        ]
        ranked = sorted(scored, key=lambda s: (-(s.value or 0.0), s.symbol or ""))[
            : int(p["top_n"])
        ]
        weights = equal_weights([s.symbol for s in ranked if s.symbol], float(p["gross"]))
        return TargetResult(
            weights,
            dict(ctx.state),
            [f"top {len(weights)} of {len(scored)} positive-momentum names"],
        )

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least lookback+5 sessions",
            "signal": f"return from t-{p['lookback']} to t-{p['skip']} (skips the most recent month)",
            "ranking": f"descending score; top {p['top_n']} with score > {p['min_return']}",
            "sizing": f"equal weight, gross {p['gross']:.0%}",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
