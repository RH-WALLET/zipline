"""MarketDataService: cached historical bars + aligned price panels for strategies.

Caching rule: bars are fetched incrementally from the last cached session onward. History
that is already cached is never re-downloaded unless explicitly invalidated (e.g. after a
split changes the adjusted series).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from zipline_engine.core.calendar import sessions_between
from zipline_engine.db.models import HistoricalBar
from zipline_engine.marketdata.base import (
    Bar,
    HistoricalMarketDataProvider,
    ProviderFetchError,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Panel:
    """Aligned daily panels: rows are sessions (ascending), columns are symbols."""

    close: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    open: pd.DataFrame
    volume: pd.DataFrame
    provider: str
    data_kind: str = "UNDERLYING_EQUITY_DAILY"

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    @property
    def last_session(self) -> date | None:
        if self.close.empty:
            return None
        return self.close.index[-1].date()

    def __len__(self) -> int:
        return len(self.close)

    def with_symbols(self, symbols: list[str]) -> Panel:
        cols = [s for s in symbols if s in self.close.columns]
        return Panel(
            self.close[cols],
            self.high[cols],
            self.low[cols],
            self.open[cols],
            self.volume[cols],
            self.provider,
            self.data_kind,
        )


@dataclass
class RefreshReport:
    provider: str
    fetched: dict[str, int] = field(default_factory=dict)
    unchanged: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)

    @property
    def total_new_bars(self) -> int:
        return sum(self.fetched.values())


class MarketDataService:
    def __init__(
        self,
        session: Session,
        provider: HistoricalMarketDataProvider,
        lookback_days: int = 420,
    ) -> None:
        self.session = session
        self.provider = provider
        self.lookback_days = lookback_days

    # ---------------------------------------------------------------- cache state
    def cached_range(self, symbol: str) -> tuple[date | None, date | None]:
        rows = (
            self.session.execute(
                select(HistoricalBar.session_date)
                .where(HistoricalBar.symbol == symbol, HistoricalBar.provider == self.provider.name)
                .order_by(HistoricalBar.session_date)
            )
            .scalars()
            .all()
        )
        if not rows:
            return None, None
        return rows[0], rows[-1]

    def invalidate(self, symbol: str) -> int:
        res = self.session.execute(
            delete(HistoricalBar).where(
                HistoricalBar.symbol == symbol, HistoricalBar.provider == self.provider.name
            )
        )
        self.session.flush()
        return int(getattr(res, "rowcount", 0) or 0)

    # ---------------------------------------------------------------- refresh
    def refresh(self, symbols: list[str], as_of: date, force_full: bool = False) -> RefreshReport:
        report = RefreshReport(provider=self.provider.name)
        default_start = as_of - timedelta(days=int(self.lookback_days * 1.6))
        for symbol in sorted(set(s.upper() for s in symbols)):
            if force_full:
                self.invalidate(symbol)
            first, last = self.cached_range(symbol)
            start = default_start if last is None else last + timedelta(days=1)
            if last is not None and last >= as_of:
                report.unchanged.append(symbol)
                continue
            if last is not None and not sessions_between(start, as_of):
                report.unchanged.append(symbol)
                continue
            try:
                bars = self.provider.fetch_daily_bars(symbol, start, as_of)
            except ProviderFetchError as e:
                log.warning("history fetch failed for %s: %s", symbol, e)
                report.failed[symbol] = str(e)
                if last is None:
                    report.unavailable.append(symbol)
                continue
            n = self._store(bars)
            if n == 0 and last is None:
                report.unavailable.append(symbol)
            report.fetched[symbol] = n
        self.session.flush()
        return report

    def _store(self, bars: list[Bar]) -> int:
        if not bars:
            return 0
        symbol = bars[0].symbol
        existing = set(
            self.session.execute(
                select(HistoricalBar.session_date).where(
                    HistoricalBar.symbol == symbol,
                    HistoricalBar.provider == self.provider.name,
                    HistoricalBar.session_date >= bars[0].session_date,
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for b in bars:
            if b.session_date in existing:
                continue
            self.session.add(
                HistoricalBar(
                    symbol=b.symbol,
                    provider=self.provider.name,
                    session_date=b.session_date,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                )
            )
            n += 1
        return n

    # ---------------------------------------------------------------- panels
    def load_panel(self, symbols: list[str], end: date, lookback_days: int | None = None) -> Panel:
        lookback = lookback_days or self.lookback_days
        start = end - timedelta(days=int(lookback * 1.6))
        rows = (
            self.session.execute(
                select(HistoricalBar).where(
                    HistoricalBar.symbol.in_([s.upper() for s in symbols]),
                    HistoricalBar.provider == self.provider.name,
                    HistoricalBar.session_date >= start,
                    HistoricalBar.session_date <= end,
                )
            )
            .scalars()
            .all()
        )
        return panel_from_bars(
            [Bar(r.symbol, r.session_date, r.open, r.high, r.low, r.close, r.volume) for r in rows],
            provider=self.provider.name,
        )


def panel_from_bars(bars: list[Bar], provider: str = "test") -> Panel:
    if not bars:
        empty = pd.DataFrame()
        return Panel(empty, empty, empty, empty, empty, provider)
    frame = pd.DataFrame(
        {
            "symbol": [b.symbol for b in bars],
            "date": [pd.Timestamp(b.session_date) for b in bars],
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) for b in bars],
        }
    )
    frame = frame.drop_duplicates(["symbol", "date"], keep="last")

    def pv(col: str) -> pd.DataFrame:
        p = frame.pivot(index="date", columns="symbol", values=col).sort_index()
        p.columns = [str(c) for c in p.columns]
        return p[sorted(p.columns)]

    return Panel(pv("close"), pv("high"), pv("low"), pv("open"), pv("volume"), provider)
