"""Run a strategy through zipline-reloaded's simulator against the cached-bars bundle."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from zipline_engine.config import get_settings
from zipline_engine.core.calendar import nyse
from zipline_engine.strategies.registry import build_strategy
from zipline_engine.zipline_bridge.algorithm import make_algorithm
from zipline_engine.zipline_bridge.bundle import (
    BUNDLE_NAME,
    ingest,
    is_ingested,
    load_bars,
    register_bundle,
)

log = logging.getLogger(__name__)


def run_backtest(
    code: str,
    start: date,
    end: date,
    *,
    capital_base: float = 10_000.0,
    bundle: str = BUNDLE_NAME,
    universe: list[str] | None = None,
) -> dict[str, Any]:
    import empyrical as ep
    from zipline import run_algorithm

    register_bundle(bundle)
    if not is_ingested(bundle):
        ingest(bundle)
    settings = get_settings()
    strategy = build_strategy(code)
    syms = universe or settings.allowlist
    lookback = strategy.min_history() + 10
    initialize, _ = make_algorithm(strategy, syms, lookback=lookback)
    # the simulator needs ``lookback`` sessions of bars before the first rebalance
    bars = load_bars(settings.history_provider)
    first_bar = bars["date"].min()
    cal = nyse()
    sessions = cal.sessions_in_range(first_bar, pd.Timestamp(end))
    earliest = sessions[min(lookback, len(sessions) - 1)]
    requested_start = pd.Timestamp(start)
    effective_start = max(requested_start, earliest)
    if effective_start >= pd.Timestamp(end):
        raise ValueError(
            f"not enough cached history: earliest backtest start with {lookback} sessions of lookback is {earliest.date()}"
        )
    perf = run_algorithm(
        start=effective_start,
        end=pd.Timestamp(end),
        initialize=initialize,
        capital_base=capital_base,
        bundle=bundle,
        data_frequency="daily",
    )
    returns = perf["returns"]
    return {
        "strategy": code,
        "version_hash": strategy.get_version_hash(),
        "requested_start": str(requested_start.date()),
        "start": str(perf.index[0].date()),
        "end": str(perf.index[-1].date()),
        "sessions": int(len(perf)),
        "capital_base": capital_base,
        "ending_value": float(perf["portfolio_value"].iloc[-1]),
        "total_return_pct": float(ep.cum_returns_final(returns) * 100),
        "annual_return_pct": float(ep.annual_return(returns) * 100),
        "annual_volatility_pct": float(ep.annual_volatility(returns) * 100),
        "sharpe": float(ep.sharpe_ratio(returns)) if returns.std() > 0 else None,
        "max_drawdown_pct": float(ep.max_drawdown(returns) * 100),
        "transactions": int(sum(len(t) for t in perf["transactions"])),
        "data": "underlying equity daily bars from the engine cache; Zipline FixedBasisPointsSlippage(5 bps), zero commission",
    }
