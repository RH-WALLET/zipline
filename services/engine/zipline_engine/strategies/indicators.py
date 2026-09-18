"""Deterministic indicator math on daily panels (pandas, float64). No randomness, no fitting."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def sma(close: pd.DataFrame, window: int) -> pd.DataFrame:
    return close.rolling(window, min_periods=window).mean()


def pct_return(close: pd.DataFrame, periods: int) -> pd.DataFrame:
    return close / close.shift(periods) - 1.0


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(np.log(close / close.shift(1)), index=close.index, columns=close.columns)


def realized_vol(close: pd.DataFrame, window: int, annualize: bool = True) -> pd.DataFrame:
    vol = log_returns(close).rolling(window, min_periods=window).std(ddof=1)
    return vol * np.sqrt(TRADING_DAYS) if annualize else vol


def donchian_high(high: pd.DataFrame, window: int) -> pd.DataFrame:
    """Highest high of the PRIOR ``window`` sessions (excludes today)."""
    return high.shift(1).rolling(window, min_periods=window).max()


def donchian_low(low: pd.DataFrame, window: int) -> pd.DataFrame:
    return low.shift(1).rolling(window, min_periods=window).min()


def zscore(series: pd.DataFrame, window: int) -> pd.DataFrame:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std(ddof=1)
    return (series - mean) / std.replace(0.0, np.nan)


def atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, window: int) -> pd.DataFrame:
    prev_close = close.shift(1)
    tr = (
        pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=0)
        .groupby(level=0)
        .max()
    )
    return tr.rolling(window, min_periods=window).mean()


def last_valid(frame: pd.DataFrame, symbol: str) -> float | None:
    if symbol not in frame.columns or frame.empty:
        return None
    v = frame[symbol].iloc[-1]
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def history_length(close: pd.DataFrame, symbol: str) -> int:
    if symbol not in close.columns:
        return 0
    return int(close[symbol].notna().sum())
