"""REVERSAL — short-horizon loser reversal, rebalanced every N sessions."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    equal_weights,
)
from zipline_engine.strategies.indicators import last_valid, pct_return


class ReversalStrategy(Strategy):
    code = "REVERSAL"
    name = "Reversal"
    description = "Every 5 sessions, buys the worst-performing eligible assets over the prior 5 sessions and holds them equal-weighted until the next rebalance."
    default_params: dict[str, Any] = {
        "lookback": 5,
        "bottom_n": 3,
        "hold_sessions": 5,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["lookback"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        ret = pct_return(self.closes(ctx, symbols), int(p["lookback"]))
        out: list[Signal] = []
        for s in symbols:
            v = last_valid(ret, s)
            if v is None:
                continue
            out.append(Signal("SHORT_TERM_RETURN", s, v, {"return": round(v, 6)}))
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        hold = int(p["hold_sessions"])
        last = ctx.state.get("last_rebalance_ordinal")
        due = last is None or (ctx.session_ordinal - int(last)) >= hold
        held = [s for s in ctx.state.get("held", []) if s in ctx.universe]
        if not due and held:
            return TargetResult(
                equal_weights(held, float(p["gross"])),
                dict(ctx.state),
                ["holding until next rebalance"],
            )
        ranked = sorted(
            (s for s in signals if s.kind == "SHORT_TERM_RETURN"),
            key=lambda s: (s.value or 0.0, s.symbol or ""),
        )
        chosen = [s.symbol for s in ranked[: int(p["bottom_n"])] if s.symbol]
        weights = equal_weights(chosen, float(p["gross"]))
        new_state = dict(ctx.state)
        new_state["held"] = sorted(weights.keys())
        new_state["last_rebalance_ordinal"] = ctx.session_ordinal
        return TargetResult(weights, new_state, [f"rebalanced into {len(weights)} losers"])

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least lookback+5 sessions",
            "signal": f"{p['lookback']}-session price return",
            "ranking": f"ascending; the {p['bottom_n']} worst performers",
            "sizing": f"equal weight, gross {p['gross']:.0%}",
            "rebalance": f"every {p['hold_sessions']} sessions after the US close (positions carried between rebalances)",
            "state": "held symbols and the session ordinal of the last rebalance (persisted)",
            "parameters": p,
        }
