"""LOWVOL — low-volatility selection."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    inverse_vol_weights,
)
from zipline_engine.strategies.indicators import last_valid, realized_vol


class LowVolStrategy(Strategy):
    code = "LOWVOL"
    name = "Low Volatility"
    description = "Holds the least volatile eligible assets over the trailing 60 sessions, weighted by inverse volatility."
    default_params: dict[str, Any] = {"vol_days": 60, "top_n": 5, "max_weight": 0.35, "gross": 1.0}

    def min_history(self) -> int:
        return int(self.params["vol_days"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        vol = realized_vol(self.closes(ctx, symbols), int(p["vol_days"]))
        out: list[Signal] = []
        for s in symbols:
            v = last_valid(vol, s)
            if v is None or v <= 0:
                continue
            out.append(Signal("VOLATILITY", s, v, {"vol": round(v, 6)}))
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        ranked = sorted(
            (s for s in signals if s.kind == "VOLATILITY"),
            key=lambda s: (s.value or 0.0, s.symbol or ""),
        )
        chosen = ranked[: int(p["top_n"])]
        vols = {s.symbol: (s.value or 0.0) for s in chosen if s.symbol}
        weights = inverse_vol_weights(vols, float(p["gross"]), float(p["max_weight"]))
        return TargetResult(
            weights, dict(ctx.state), [f"lowest-vol {len(weights)} of {len(ranked)}"]
        )

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least vol_days+5 sessions",
            "signal": f"annualized standard deviation of daily log returns over {p['vol_days']} sessions",
            "ranking": f"ascending volatility; lowest {p['top_n']}",
            "sizing": f"inverse volatility, per-name cap {p['max_weight']:.0%}, gross {p['gross']:.0%}",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
