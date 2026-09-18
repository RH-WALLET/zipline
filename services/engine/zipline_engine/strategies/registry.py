"""The ten strategies. Order here is the display order everywhere."""

from __future__ import annotations

from typing import Any

from zipline_engine.strategies.base import Strategy
from zipline_engine.strategies.breakout import BreakoutStrategy
from zipline_engine.strategies.dualma import DualMovingAverageStrategy
from zipline_engine.strategies.lowvol import LowVolStrategy
from zipline_engine.strategies.meanrev import MeanReversionStrategy
from zipline_engine.strategies.momentum import MomentumStrategy
from zipline_engine.strategies.pairs import PairsStrategy
from zipline_engine.strategies.reversal import ReversalStrategy
from zipline_engine.strategies.riskon import RiskOnStrategy
from zipline_engine.strategies.trend import TrendStrategy
from zipline_engine.strategies.zeroiq import ZeroIQStrategy

STRATEGY_CLASSES: list[type[Strategy]] = [
    TrendStrategy,
    MomentumStrategy,
    MeanReversionStrategy,
    BreakoutStrategy,
    LowVolStrategy,
    ReversalStrategy,
    DualMovingAverageStrategy,
    RiskOnStrategy,
    PairsStrategy,
    ZeroIQStrategy,
]

BY_CODE: dict[str, type[Strategy]] = {cls.code: cls for cls in STRATEGY_CLASSES}


def build_strategy(code: str, params: dict[str, Any] | None = None) -> Strategy:
    try:
        cls = BY_CODE[code.upper()]
    except KeyError as e:
        raise KeyError(f"unknown strategy {code!r}; known: {sorted(BY_CODE)}") from e
    return cls(params)


def all_strategies(param_overrides: dict[str, dict[str, Any]] | None = None) -> list[Strategy]:
    overrides = param_overrides or {}
    return [cls(overrides.get(cls.code)) for cls in STRATEGY_CLASSES]
