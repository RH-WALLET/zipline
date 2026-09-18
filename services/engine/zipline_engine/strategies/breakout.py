"""BREAKOUT — Donchian price-channel breakout."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    inverse_vol_weights,
)
from zipline_engine.strategies.indicators import (
    donchian_high,
    donchian_low,
    last_valid,
    realized_vol,
)


class BreakoutStrategy(Strategy):
    code = "BREAKOUT"
    name = "Breakout"
    description = "Enters when the close exceeds the prior 55-day high; exits when it falls below the prior 20-day low. Positions are volatility-sized."
    default_params: dict[str, Any] = {
        "entry_window": 55,
        "exit_window": 20,
        "vol_days": 20,
        "max_positions": 5,
        "max_weight": 0.35,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["entry_window"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        close = self.closes(ctx, symbols)
        high, low = ctx.panel.high[symbols].ffill(), ctx.panel.low[symbols].ffill()
        upper, lower = (
            donchian_high(high, int(p["entry_window"])),
            donchian_low(low, int(p["exit_window"])),
        )
        vol = realized_vol(close, int(p["vol_days"]))
        held = set(ctx.state.get("held", []))
        out: list[Signal] = []
        for s in symbols:
            c, u, lo, v = (
                last_valid(close, s),
                last_valid(upper, s),
                last_valid(lower, s),
                last_valid(vol, s),
            )
            if None in (c, u, lo, v):
                continue
            assert c is not None and u is not None and lo is not None
            if s in held:
                kind = "EXIT" if c < lo else "HOLD"
            else:
                kind = "ENTRY" if c > u else "NONE"
            strength = (c - u) / u if u else 0.0
            out.append(
                Signal(
                    kind,
                    s,
                    strength,
                    {
                        "close": round(c, 4),
                        "channel_high": round(u, 4),
                        "channel_low": round(lo, 4),
                        "vol": round(v or 0.0, 6),
                    },
                )
            )
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        holds = [s for s in signals if s.kind == "HOLD"]
        entries = sorted(
            (s for s in signals if s.kind == "ENTRY"),
            key=lambda s: (-(s.value or 0.0), s.symbol or ""),
        )
        room = max(int(p["max_positions"]) - len(holds), 0)
        chosen = holds + entries[:room]
        vols = {s.symbol: s.details["vol"] for s in chosen if s.symbol and s.symbol in ctx.universe}
        weights = inverse_vol_weights(vols, float(p["gross"]), float(p["max_weight"]))
        new_state = dict(ctx.state)
        new_state["held"] = sorted(weights.keys())
        return TargetResult(
            weights, new_state, [f"{len(holds)} held, {min(room, len(entries))} breakouts"]
        )

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least entry_window+5 sessions",
            "entry": f"close > highest high of the prior {p['entry_window']} sessions",
            "exit": f"close < lowest low of the prior {p['exit_window']} sessions",
            "ranking": f"breakout strength (close / channel high - 1); up to {p['max_positions']} names",
            "sizing": f"inverse {p['vol_days']}-day volatility, per-name cap {p['max_weight']:.0%}, gross {p['gross']:.0%}",
            "state": "list of currently held symbols (persisted)",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
