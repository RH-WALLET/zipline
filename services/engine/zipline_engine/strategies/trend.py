"""TREND — medium/long-term trend following."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    inverse_vol_weights,
)
from zipline_engine.strategies.indicators import last_valid, pct_return, realized_vol, sma


class TrendStrategy(Strategy):
    code = "TREND"
    name = "Trend"
    description = "Long assets whose 50-day average is above the 200-day average, ranked by 6-month momentum, sized by inverse volatility."
    default_params: dict[str, Any] = {
        "fast": 50,
        "slow": 200,
        "momentum_days": 126,
        "vol_days": 60,
        "max_positions": 5,
        "max_weight": 0.35,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["slow"]) + 5

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        close = self.closes(ctx, symbols)
        fast, slow = sma(close, int(p["fast"])), sma(close, int(p["slow"]))
        mom, vol = (
            pct_return(close, int(p["momentum_days"])),
            realized_vol(close, int(p["vol_days"])),
        )
        out: list[Signal] = []
        for s in symbols:
            f, sl, c = last_valid(fast, s), last_valid(slow, s), last_valid(close, s)
            m, v = last_valid(mom, s), last_valid(vol, s)
            if None in (f, sl, c, m, v):
                continue
            assert f is not None and sl is not None and c is not None
            in_trend = f > sl and c > sl
            out.append(
                Signal(
                    "TREND_ON" if in_trend else "TREND_OFF",
                    s,
                    m,
                    {
                        "sma_fast": round(f, 4),
                        "sma_slow": round(sl, 4),
                        "close": round(c, 4),
                        "momentum": round(m or 0.0, 6),
                        "vol": round(v or 0.0, 6),
                    },
                )
            )
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        on = [s for s in signals if s.kind == "TREND_ON" and s.symbol]
        ranked = sorted(on, key=lambda s: (-(s.value or 0.0), s.symbol or ""))[
            : int(p["max_positions"])
        ]
        vols = {s.symbol: s.details["vol"] for s in ranked if s.symbol}
        weights = inverse_vol_weights(vols, float(p["gross"]), float(p["max_weight"]))
        return TargetResult(
            weights, dict(ctx.state), [f"{len(on)} in uptrend, holding {len(weights)}"]
        )

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least slow+5 sessions of history",
            "signal": f"SMA({p['fast']}) > SMA({p['slow']}) and close > SMA({p['slow']})",
            "ranking": f"{p['momentum_days']}-day price return, descending; top {p['max_positions']}",
            "sizing": f"inverse {p['vol_days']}-day realized volatility, per-name cap {p['max_weight']:.0%}, gross {p['gross']:.0%}",
            "exit": "asset leaves the top list or its fast average drops below the slow average",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
