"""PAIRS — long-only relative value between related eligible assets."""

from __future__ import annotations

from typing import Any

import numpy as np

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    equal_weights,
)
from zipline_engine.strategies.indicators import last_valid, log_returns, zscore


class PairsStrategy(Strategy):
    code = "PAIRS"
    name = "Pairs (long-only)"
    description = "For each configured pair whose legs are eligible and correlated, buys the leg that has underperformed when the log price ratio is more than 1.5 standard deviations from its 60-day mean. Never shorts."
    default_params: dict[str, Any] = {
        "pairs": [
            ["SPY", "QQQ"],
            ["SPY", "VTI"],
            ["AAPL", "MSFT"],
            ["GOOGL", "META"],
            ["NVDA", "AMD"],
        ],
        "corr_days": 250,
        "min_corr": 0.6,
        "z_window": 60,
        "entry_z": 1.5,
        "exit_z": 0.5,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["corr_days"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        close = self.closes(ctx, symbols)
        rets = log_returns(close)
        open_legs: dict[str, str] = dict(ctx.state.get("open", {}))  # pair_key -> long leg
        out: list[Signal] = []
        for a, b in (tuple(x) for x in p["pairs"]):
            key = f"{a}/{b}"
            if a not in symbols or b not in symbols:
                if key in open_legs:
                    out.append(Signal("PAIR_UNAVAILABLE", open_legs[key], None, {"pair": key}))
                continue
            corr_value: Any = rets[[a, b]].tail(int(p["corr_days"])).corr().iloc[0, 1]
            corr = float(corr_value)
            if np.isnan(corr) or corr < float(p["min_corr"]):
                out.append(
                    Signal(
                        "PAIR_UNCORRELATED",
                        None,
                        float(corr) if corr == corr else None,
                        {"pair": key},
                    )
                )
                continue
            ratio = np.log(close[a] / close[b]).to_frame("R")
            z = last_valid(zscore(ratio, int(p["z_window"])), "R")
            if z is None:
                continue
            current = open_legs.get(key)
            if current:
                kind = "PAIR_EXIT" if abs(z) < float(p["exit_z"]) else "PAIR_HOLD"
                out.append(
                    Signal(
                        kind,
                        current,
                        z,
                        {"pair": key, "z": round(z, 4), "corr": round(float(corr), 4)},
                    )
                )
            elif z < -float(p["entry_z"]):
                out.append(
                    Signal(
                        "PAIR_ENTRY",
                        a,
                        z,
                        {
                            "pair": key,
                            "z": round(z, 4),
                            "corr": round(float(corr), 4),
                            "cheap_leg": a,
                        },
                    )
                )
            elif z > float(p["entry_z"]):
                out.append(
                    Signal(
                        "PAIR_ENTRY",
                        b,
                        z,
                        {
                            "pair": key,
                            "z": round(z, 4),
                            "corr": round(float(corr), 4),
                            "cheap_leg": b,
                        },
                    )
                )
            else:
                out.append(
                    Signal(
                        "PAIR_NEUTRAL",
                        None,
                        z,
                        {"pair": key, "z": round(z, 4), "corr": round(float(corr), 4)},
                    )
                )
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        open_legs: dict[str, str] = {}
        for s in signals:
            if s.kind in ("PAIR_HOLD", "PAIR_ENTRY") and s.symbol and s.symbol in ctx.universe:
                open_legs[s.details["pair"]] = s.symbol
        legs = sorted(set(open_legs.values()))
        weights = equal_weights(legs, float(self.params["gross"]))
        new_state = dict(ctx.state)
        new_state["open"] = dict(sorted(open_legs.items()))
        return TargetResult(weights, new_state, [f"{len(open_legs)} pairs open"])

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "configured candidate pairs whose legs are both eligible",
            "filter": f"{p['corr_days']}-day correlation of daily log returns >= {p['min_corr']}",
            "signal": f"z-score of log(price_A / price_B) against its {p['z_window']}-day mean and standard deviation",
            "entry": f"z < -{p['entry_z']}: long A (A is cheap vs B); z > {p['entry_z']}: long B. Long-only; no short leg",
            "exit": f"|z| < {p['exit_z']}",
            "sizing": f"equal weight across open legs, gross {p['gross']:.0%}",
            "state": "open pair -> long leg (persisted)",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
