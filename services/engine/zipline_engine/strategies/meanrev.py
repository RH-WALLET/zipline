"""MEANREV — short-horizon mean reversion with a long-term trend filter."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    equal_weights,
)
from zipline_engine.strategies.indicators import last_valid, pct_return, sma, zscore


class MeanReversionStrategy(Strategy):
    code = "MEANREV"
    name = "Mean Reversion"
    description = "Buys short-term oversold assets that remain above their 200-day average; exits when the 5-day return z-score recovers above zero."
    default_params: dict[str, Any] = {
        "short_days": 5,
        "z_window": 60,
        "entry_z": -1.0,
        "exit_z": 0.0,
        "trend_days": 200,
        "max_positions": 5,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["trend_days"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        close = self.closes(ctx, symbols)
        z = zscore(pct_return(close, int(p["short_days"])), int(p["z_window"]))
        trend = sma(close, int(p["trend_days"]))
        held = set(ctx.state.get("held", []))
        out: list[Signal] = []
        for s in symbols:
            zv, tv, c = last_valid(z, s), last_valid(trend, s), last_valid(close, s)
            if zv is None or tv is None or c is None:
                continue
            above = c > tv
            if s in held:
                kind = "EXIT" if (zv > float(p["exit_z"]) or not above) else "HOLD"
            else:
                kind = "ENTRY" if (zv < float(p["entry_z"]) and above) else "NONE"
            out.append(
                Signal(kind, s, zv, {"z": round(zv, 4), "above_trend": above, "close": round(c, 4)})
            )
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        holds = sorted(s.symbol for s in signals if s.kind == "HOLD" and s.symbol)
        entries = sorted(
            (s for s in signals if s.kind == "ENTRY" and s.symbol),
            key=lambda s: (s.value or 0.0, s.symbol or ""),
        )
        room = max(int(p["max_positions"]) - len(holds), 0)
        chosen = holds + [s.symbol for s in entries[:room] if s.symbol]
        chosen = [s for s in chosen if s in ctx.universe]
        weights = equal_weights(chosen, float(p["gross"]))
        new_state = dict(ctx.state)
        new_state["held"] = sorted(weights.keys())
        return TargetResult(
            weights, new_state, [f"{len(holds)} held, {min(room, len(entries))} new entries"]
        )

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least trend_days+5 sessions",
            "signal": f"z-score of the {p['short_days']}-day return against its {p['z_window']}-day distribution",
            "entry": f"z < {p['entry_z']} and close > SMA({p['trend_days']}); most oversold first, up to {p['max_positions']} names",
            "exit": f"z > {p['exit_z']} or close falls below SMA({p['trend_days']})",
            "sizing": f"equal weight, gross {p['gross']:.0%}",
            "state": "list of currently held symbols (persisted)",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
