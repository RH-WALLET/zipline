"""Performance metrics in the shape Quantopian's backtest report used.

Daily return series are derived from valuation snapshots (last snapshot per session), the
benchmark is SPY's underlying close-to-close return from the historical cache, and every
statistic is computed by empyrical-reloaded. Anything that needs more history than exists
is returned as null — never estimated.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.api.deps import db, settings
from zipline_engine.config import Settings
from zipline_engine.db.models import HistoricalBar, PortfolioSnapshot, Strategy, TreasurySnapshot

router = APIRouter()

WINDOWS = OrderedDict([("1M", 21), ("3M", 63), ("6M", 126), ("12M", 252)])
BENCHMARK = "SPY"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _daily_index(points: Sequence[Any]) -> pd.Series:
    """Last time-weighted index value per session date."""
    if not points:
        return pd.Series(dtype=float)
    frame = pd.DataFrame(
        {"t": [pd.Timestamp(t) for t, _ in points], "v": [float(v) for _, v in points]}
    )
    frame["d"] = frame["t"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    daily = frame.groupby("d")["v"].last().sort_index()
    return daily


def _benchmark_returns(session: Session, provider: str, dates: pd.Index) -> pd.Series:
    if len(dates) == 0:
        return pd.Series(dtype=float)
    start = (dates[0] - pd.Timedelta(days=10)).date()
    rows = session.execute(
        select(HistoricalBar.session_date, HistoricalBar.close)
        .where(
            HistoricalBar.symbol == BENCHMARK,
            HistoricalBar.provider == provider,
            HistoricalBar.session_date >= start,
        )
        .order_by(HistoricalBar.session_date)
    ).all()
    if not rows:
        return pd.Series(dtype=float)
    close = pd.Series(
        [float(c) for _, c in rows], index=pd.DatetimeIndex([pd.Timestamp(d) for d, _ in rows])
    )
    return close.pct_change().dropna()


def _stats(returns: pd.Series, bench: pd.Series | None) -> dict[str, float | None]:
    import empyrical as ep

    out: dict[str, float | None] = {
        "total_return": None,
        "annual_return": None,
        "volatility": None,
        "sharpe": None,
        "sortino": None,
        "max_drawdown": None,
        "alpha": None,
        "beta": None,
        "information_ratio": None,
        "benchmark_return": None,
    }
    if len(returns) == 0:
        return out
    out["total_return"] = _f(ep.cum_returns_final(returns))
    out["max_drawdown"] = _f(ep.max_drawdown(returns))
    if len(returns) >= 2:
        out["annual_return"] = _f(ep.annual_return(returns))
        out["volatility"] = _f(ep.annual_volatility(returns))
        if float(returns.std()) > 0:
            out["sharpe"] = _f(ep.sharpe_ratio(returns))
            out["sortino"] = _f(ep.sortino_ratio(returns))
    if bench is not None and len(bench) > 0:
        aligned = pd.concat([returns.rename("a"), bench.rename("b")], axis=1, join="inner").dropna()
        if len(aligned) >= 1:
            out["benchmark_return"] = _f(ep.cum_returns_final(aligned["b"]))
        if len(aligned) >= 3 and float(aligned["b"].std()) > 0:
            alpha, beta = ep.alpha_beta(aligned["a"], aligned["b"])
            out["alpha"] = _f(alpha)
            out["beta"] = _f(beta)
            if float((aligned["a"] - aligned["b"]).std()) > 0:
                out["information_ratio"] = _f(ep.excess_sharpe(aligned["a"], aligned["b"]))
    return out


def _report(index: pd.Series, bench_returns: pd.Series, intraday: Sequence[Any]) -> dict[str, Any]:
    returns = index.pct_change().dropna()
    bench = (
        bench_returns.reindex(returns.index).dropna() if len(returns) else pd.Series(dtype=float)
    )
    overall = _stats(returns, bench if len(bench) else None)
    windows: dict[str, dict[str, float | None] | None] = {}
    for name, n in WINDOWS.items():
        if len(returns) >= n:
            r = returns.tail(n)
            windows[name] = _stats(r, bench.reindex(r.index).dropna() if len(bench) else None)
        else:
            windows[name] = None
    # cumulative curves (percent) on session dates; algorithm from the TWR index, benchmark from SPY
    cumulative: list[dict[str, Any]] = []
    if len(index) >= 1:
        base = float(index.iloc[0])
        bench_cum = (1 + bench).cumprod() - 1 if len(bench) else pd.Series(dtype=float)
        for raw_d, v in index.items():
            d = pd.Timestamp(str(raw_d))
            pt: dict[str, Any] = {
                "date": d.date().isoformat(),
                "algorithm": (float(v) / base - 1) * 100 if base else 0.0,
            }
            if len(bench_cum) and d in bench_cum.index:
                pt["benchmark"] = float(bench_cum[d]) * 100
            elif d == pd.Timestamp(str(index.index[0])):
                pt["benchmark"] = 0.0
            cumulative.append(pt)
    # intraday valuations (all snapshots) so the curve is alive before the first full session closes
    intraday_pts = []
    if intraday:
        base_i = float(intraday[0][1])
        for t, v in intraday:
            intraday_pts.append(
                {
                    "t": pd.Timestamp(t).isoformat(),
                    "algorithm": (float(v) / base_i - 1) * 100 if base_i else 0.0,
                }
            )
    return {
        "sessions": int(len(returns)),
        "benchmark": BENCHMARK,
        "overall": overall,
        "windows": windows,
        "cumulative": cumulative,
        "intraday": intraday_pts,
        "note": "returns are time-weighted (flows excluded); benchmark is SPY underlying close-to-close; statistics by empyrical-reloaded; null means not enough history",
    }


@router.get("/treasury/metrics")
def treasury_metrics(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    rows = session.execute(
        select(TreasurySnapshot.taken_at, TreasurySnapshot.twr_index).order_by(
            TreasurySnapshot.taken_at
        )
    ).all()
    index = _daily_index(rows)
    bench = _benchmark_returns(
        session, cfg.history_provider, index.index if len(index) else pd.DatetimeIndex([])
    )
    return _report(index, bench, rows)


@router.get("/strategies/{code}/metrics")
def strategy_metrics(
    code: str, session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    strat = session.execute(
        select(Strategy).where(Strategy.code == code.upper())
    ).scalar_one_or_none()
    if strat is None:
        raise HTTPException(404, f"unknown strategy {code}")
    rows = session.execute(
        select(PortfolioSnapshot.taken_at, PortfolioSnapshot.twr_index)
        .where(PortfolioSnapshot.strategy_id == strat.id)
        .order_by(PortfolioSnapshot.taken_at)
    ).all()
    index = _daily_index(rows)
    bench = _benchmark_returns(
        session, cfg.history_provider, index.index if len(index) else pd.DatetimeIndex([])
    )
    return _report(index, bench, rows)
