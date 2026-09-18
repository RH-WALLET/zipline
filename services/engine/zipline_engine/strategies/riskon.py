"""RISKON — trend following gated by a deterministic volatility regime filter."""

from __future__ import annotations

from typing import Any

import pandas as pd

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    inverse_vol_weights,
)
from zipline_engine.strategies.indicators import last_valid, pct_return, realized_vol, sma


class RiskOnStrategy(Strategy):
    code = "RISKON"
    name = "Risk-On"
    description = "Fully invested in a trend basket only when the benchmark is above its 200-day average and its 20-day volatility is below the regime threshold; otherwise 100% cash."
    default_params: dict[str, Any] = {
        "regime_sma": 200,
        "regime_vol_days": 20,
        "max_regime_vol": 0.25,
        "trend_sma": 50,
        "momentum_days": 63,
        "vol_days": 60,
        "top_n": 4,
        "max_weight": 0.4,
        "gross": 1.0,
    }

    def min_history(self) -> int:
        return int(self.params["regime_sma"]) + 5

    def _benchmark_series(self, ctx: StrategyContext, symbols: list[str]) -> tuple[pd.Series, str]:
        close = self.closes(ctx, symbols)
        if ctx.benchmark and ctx.benchmark in close.columns:
            return close[ctx.benchmark], ctx.benchmark
        # equal-weight index of the eligible universe (normalized to 100 at first common date)
        norm = close / close.bfill().iloc[0]
        return norm.mean(axis=1), "EQUAL_WEIGHT_UNIVERSE"

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        symbols = self.usable(ctx)
        if not symbols:
            return [Signal("INSUFFICIENT_HISTORY", details={"need": self.min_history()})]
        bench, bench_name = self._benchmark_series(ctx, symbols)
        bdf = bench.to_frame("B")
        b_sma = last_valid(sma(bdf, int(p["regime_sma"])), "B")
        b_vol = last_valid(realized_vol(bdf, int(p["regime_vol_days"])), "B")
        b_close = last_valid(bdf, "B")
        if None in (b_sma, b_vol, b_close):
            return [Signal("INSUFFICIENT_HISTORY", details={"benchmark": bench_name})]
        assert b_sma is not None and b_vol is not None and b_close is not None
        risk_on = b_close > b_sma and b_vol < float(p["max_regime_vol"])
        out = [
            Signal(
                "REGIME_ON" if risk_on else "REGIME_OFF",
                None,
                b_vol,
                {
                    "benchmark": bench_name,
                    "close": round(b_close, 4),
                    "sma": round(b_sma, 4),
                    "vol": round(b_vol, 6),
                    "max_vol": p["max_regime_vol"],
                },
            )
        ]
        close = self.closes(ctx, symbols)
        t_sma, mom, vol = (
            sma(close, int(p["trend_sma"])),
            pct_return(close, int(p["momentum_days"])),
            realized_vol(close, int(p["vol_days"])),
        )
        for s in symbols:
            c, ts, m, v = (
                last_valid(close, s),
                last_valid(t_sma, s),
                last_valid(mom, s),
                last_valid(vol, s),
            )
            if None in (c, ts, m, v):
                continue
            assert c is not None and ts is not None
            out.append(
                Signal(
                    "CANDIDATE" if c > ts else "BELOW_TREND",
                    s,
                    m,
                    {"momentum": round(m or 0.0, 6), "vol": round(v or 0.0, 6)},
                )
            )
        return out

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        regime_on = any(s.kind == "REGIME_ON" for s in signals)
        if not regime_on:
            return TargetResult({}, dict(ctx.state), ["regime off: 100% cash"])
        cands = sorted(
            (s for s in signals if s.kind == "CANDIDATE"),
            key=lambda s: (-(s.value or 0.0), s.symbol or ""),
        )[: int(p["top_n"])]
        vols = {s.symbol: s.details["vol"] for s in cands if s.symbol}
        weights = inverse_vol_weights(vols, float(p["gross"]), float(p["max_weight"]))
        return TargetResult(weights, dict(ctx.state), [f"regime on: {len(weights)} names"])

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "eligible Stock Tokens with at least regime_sma+5 sessions",
            "regime": f"benchmark (SPY if eligible, else equal-weight universe) close > SMA({p['regime_sma']}) AND {p['regime_vol_days']}-day realized vol < {p['max_regime_vol']:.0%}",
            "signal": f"close > SMA({p['trend_sma']}); ranked by {p['momentum_days']}-day return; top {p['top_n']}",
            "sizing": f"inverse {p['vol_days']}-day volatility, per-name cap {p['max_weight']:.0%}; 0% when regime is off",
            "rebalance": "daily after the US close",
            "parameters": p,
        }
