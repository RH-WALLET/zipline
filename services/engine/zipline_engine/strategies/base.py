"""Strategy interface.

A strategy is a pure function of (history panel, eligible universe, persisted state, params)
to (signals, target weights of its own sleeve NAV, new state). Same inputs -> same outputs.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any

import pandas as pd

from zipline_engine.marketdata.service import Panel

WEIGHT_PLACES = Decimal("1e-8")


@dataclass(frozen=True)
class StrategyContext:
    session_date: date
    universe: list[str]
    panel: Panel
    current_weights: dict[str, Decimal]
    state: dict[str, Any]
    params: dict[str, Any]
    benchmark: str | None = None
    session_ordinal: int = 0


@dataclass(frozen=True)
class Signal:
    kind: str
    symbol: str | None = None
    value: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetResult:
    weights: dict[str, Decimal]
    new_state: dict[str, Any]
    notes: list[str] = field(default_factory=list)


@dataclass
class StrategyOutput:
    signals: list[Signal]
    target_weights: dict[str, Decimal]
    new_state: dict[str, Any]
    notes: list[str]


def _q(w: float) -> Decimal:
    return Decimal(repr(float(w))).quantize(WEIGHT_PLACES, rounding=ROUND_DOWN)


def normalize_weights(
    raw: dict[str, float], gross: float = 1.0, cap: float | None = None
) -> dict[str, Decimal]:
    """Scale positive raw weights to sum to ``gross`` (<= 1), optional per-name cap, deterministic order."""
    positive = {s: w for s, w in raw.items() if w is not None and w > 0 and w == w}
    if not positive or gross <= 0:
        return {}
    total = sum(positive.values())
    scaled = {s: w / total * gross for s, w in positive.items()}
    if cap is not None and cap > 0:
        # iterative capping: redistribute excess proportionally to uncapped names
        for _ in range(len(scaled)):
            over = {s: w for s, w in scaled.items() if w > cap + 1e-12}
            if not over:
                break
            excess = sum(w - cap for w in over.values())
            for s in over:
                scaled[s] = cap
            under = {s: w for s, w in scaled.items() if s not in over}
            under_total = sum(under.values())
            if under_total <= 0:
                break
            for s in under:
                scaled[s] += excess * under[s] / under_total
    out = {s: _q(w) for s, w in sorted(scaled.items())}
    return {s: w for s, w in out.items() if w > 0}


def equal_weights(symbols: list[str], gross: float = 1.0) -> dict[str, Decimal]:
    if not symbols:
        return {}
    return normalize_weights(dict.fromkeys(sorted(symbols), 1.0), gross)


def inverse_vol_weights(
    vols: dict[str, float], gross: float = 1.0, cap: float | None = None
) -> dict[str, Decimal]:
    raw = {s: 1.0 / v for s, v in vols.items() if v is not None and v > 0 and v == v}
    return normalize_weights(raw, gross, cap)


class Strategy(ABC):
    code: str = "BASE"
    name: str = "Base"
    description: str = ""
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        merged = dict(self.default_params)
        merged.update(params or {})
        self.params = merged

    # ------------------------------------------------------------- interface
    @abstractmethod
    def generate_signals(self, ctx: StrategyContext) -> list[Signal]: ...

    @abstractmethod
    def calculate_target_weights(
        self, ctx: StrategyContext, signals: list[Signal]
    ) -> TargetResult: ...

    @abstractmethod
    def describe_rules(self) -> dict[str, Any]: ...

    def min_history(self) -> int:
        return 60

    def run(self, ctx: StrategyContext) -> StrategyOutput:
        signals = self.generate_signals(ctx)
        result = self.calculate_target_weights(ctx, signals)
        total = sum(result.weights.values(), Decimal(0))
        if total > Decimal("1.00000001"):
            raise ValueError(f"{self.code}: target weights sum to {total} > 1 (no leverage)")
        for s, w in result.weights.items():
            if w < 0:
                raise ValueError(f"{self.code}: negative weight for {s} (long-only)")
            if s not in ctx.universe:
                raise ValueError(f"{self.code}: weight for {s} outside eligible universe")
        return StrategyOutput(signals, result.weights, result.new_state, result.notes)

    # ------------------------------------------------------------- provenance
    def source_hash(self) -> str:
        src = inspect.getsource(type(self)).encode()
        return hashlib.sha256(src).hexdigest()[:16]

    def get_version_hash(self) -> str:
        payload = json.dumps(self.params, sort_keys=True, default=str).encode()
        return hashlib.sha256(self.source_hash().encode() + payload).hexdigest()[:16]

    # ------------------------------------------------------------- helpers
    def usable(self, ctx: StrategyContext, need: int | None = None) -> list[str]:
        """Symbols in the eligible universe with at least ``need`` valid closes."""
        from zipline_engine.strategies.indicators import history_length

        need = need or self.min_history()
        close = ctx.panel.close
        return sorted(s for s in ctx.universe if history_length(close, s) >= need)

    @staticmethod
    def closes(ctx: StrategyContext, symbols: list[str]) -> pd.DataFrame:
        return ctx.panel.close[symbols].ffill()
