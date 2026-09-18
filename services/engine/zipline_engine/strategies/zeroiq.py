"""ZEROIQ — control strategy driven by a persisted PRNG seed.

This is the experimental control group, not a model: its decisions are drawn from
``numpy.random.Generator(PCG64)`` seeded with (persisted seed, session ordinal). Given the
same seed, session and sorted eligible universe, it reproduces the same portfolio exactly.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from zipline_engine.strategies.base import (
    Signal,
    Strategy,
    StrategyContext,
    TargetResult,
    normalize_weights,
)


def derive_stream_seed(seed: int, session_ordinal: int, universe: list[str]) -> int:
    h = hashlib.sha256(f"{seed}|{session_ordinal}|{','.join(sorted(universe))}".encode()).digest()
    return int.from_bytes(h[:8], "big")


class ZeroIQStrategy(Strategy):
    code = "ZEROIQ"
    name = "Zero IQ (control)"
    description = "Control group. Every 5 sessions picks 3 eligible assets uniformly at random from a persisted seed and assigns random weights. No information is used."
    default_params: dict[str, Any] = {
        "n_positions": 3,
        "hold_sessions": 5,
        "min_gross": 0.5,
        "max_gross": 1.0,
    }

    def min_history(self) -> int:
        return 1

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        seed = ctx.state.get("seed")
        if seed is None:
            return [
                Signal(
                    "SEED_MISSING",
                    details={"note": "seed is created by the cycle runner and persisted"},
                )
            ]
        stream = derive_stream_seed(int(seed), ctx.session_ordinal, ctx.universe)
        return [
            Signal(
                "PRNG_STREAM",
                None,
                None,
                {
                    "seed": str(int(seed)),
                    "session_ordinal": ctx.session_ordinal,
                    "stream_seed": str(stream),
                    "universe": sorted(ctx.universe),
                },
            )
        ]

    def calculate_target_weights(self, ctx: StrategyContext, signals: list[Signal]) -> TargetResult:
        p = self.params
        stream_sig = next((s for s in signals if s.kind == "PRNG_STREAM"), None)
        if stream_sig is None or not ctx.universe:
            return TargetResult({}, dict(ctx.state), ["no seed or empty universe: cash"])
        last = ctx.state.get("last_rebalance_ordinal")
        held_state = ctx.state.get("held_weights", {})
        held = (
            {s: w for s, w in held_state.items() if s in ctx.universe}
            if isinstance(held_state, dict)
            else {}
        )
        due = last is None or (ctx.session_ordinal - int(last)) >= int(p["hold_sessions"])
        if not due and held:
            weights = normalize_weights(
                {s: float(w) for s, w in held.items()}, sum(float(w) for w in held.values())
            )
            return TargetResult(weights, dict(ctx.state), ["holding random book until next draw"])
        rng = np.random.Generator(np.random.PCG64(int(stream_sig.details["stream_seed"])))
        universe = sorted(ctx.universe)
        n = min(int(p["n_positions"]), len(universe))
        picks = sorted(rng.choice(universe, size=n, replace=False).tolist())
        raw = rng.dirichlet(np.ones(n)).tolist()
        gross = float(rng.uniform(float(p["min_gross"]), float(p["max_gross"])))
        weights = normalize_weights(dict(zip(picks, raw, strict=True)), gross)
        new_state = dict(ctx.state)
        new_state["held_weights"] = {s: str(w) for s, w in weights.items()}
        new_state["last_rebalance_ordinal"] = ctx.session_ordinal
        new_state["last_stream_seed"] = str(stream_sig.details["stream_seed"])
        return TargetResult(weights, new_state, [f"random draw: {picks} gross {gross:.2f}"])

    def describe_rules(self) -> dict[str, Any]:
        p = self.params
        return {
            "universe": "all eligible Stock Tokens (sorted)",
            "signal": "none. A PCG64 generator seeded with sha256(seed | session ordinal | sorted universe)",
            "selection": f"{p['n_positions']} symbols drawn uniformly without replacement",
            "sizing": f"Dirichlet(1,...,1) weights scaled to a uniform gross exposure in [{p['min_gross']}, {p['max_gross']}]",
            "rebalance": f"every {p['hold_sessions']} sessions",
            "state": "seed (created once, persisted), held weights, last rebalance ordinal, last stream seed",
            "purpose": "control group against which the rule-based sleeves can be compared",
            "parameters": p,
        }
