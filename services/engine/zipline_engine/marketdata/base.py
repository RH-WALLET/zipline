"""Historical market data provider interface.

Providers return daily OHLCV bars of the UNDERLYING US equity (split-adjusted). These are
NOT Robinhood Chain prices; they are used only to compute deterministic signals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class HistoricalMarketDataProvider(ABC):
    """Swappable source of daily underlying-equity bars."""

    name: str = "abstract"
    data_kind: str = "UNDERLYING_EQUITY_DAILY"

    @abstractmethod
    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Return bars with ``start <= session_date <= end``, ascending. Empty list if none."""

    def describe(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.data_kind}


class ProviderConfigurationError(RuntimeError):
    """Raised when a provider is selected but its credentials/config are missing."""


class ProviderFetchError(RuntimeError):
    """Raised when a provider request fails; the caller decides whether to use cached data."""
