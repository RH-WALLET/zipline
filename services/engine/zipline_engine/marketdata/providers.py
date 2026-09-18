"""Concrete HistoricalMarketDataProvider implementations.

* ``YFinanceProvider``   – dev default. Unofficial Yahoo Finance data via ``yfinance``.
* ``StooqProvider``      – free CSV download, no key.
* ``PolygonProvider``    – https://polygon.io  (POLYGON_API_KEY)
* ``AlpacaProvider``     – https://alpaca.markets market data v2 (ALPACA_API_KEY/SECRET)
* ``TwelveDataProvider`` – https://twelvedata.com (TWELVEDATA_API_KEY)

Every keyed provider raises ``ProviderConfigurationError`` at construction when its key is
missing. Nothing here ever fabricates a bar.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx

from zipline_engine.core.money import D
from zipline_engine.marketdata.base import (
    Bar,
    HistoricalMarketDataProvider,
    ProviderConfigurationError,
    ProviderFetchError,
)

log = logging.getLogger(__name__)


def _bar(
    symbol: str, day: date, o: object, h: object, lo: object, c: object, v: object
) -> Bar | None:
    try:
        o_, h_, l_, c_ = D(o), D(h), D(lo), D(c)
    except (InvalidOperation, ValueError):
        return None
    if any(x is None or x != x or x <= 0 for x in (o_, h_, l_, c_)):  # NaN or non-positive
        return None
    try:
        vol = D(v) if v is not None and v == v else Decimal(0)
    except (InvalidOperation, ValueError):
        vol = Decimal(0)
    return Bar(symbol.upper(), day, o_, h_, l_, c_, vol)


class YFinanceProvider(HistoricalMarketDataProvider):
    name = "yfinance"

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        try:
            import yfinance as yf
        except ImportError as e:  # pragma: no cover
            raise ProviderConfigurationError("yfinance is not installed") from e
        try:
            hist = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
        except Exception as e:  # network / symbol errors
            raise ProviderFetchError(f"yfinance fetch failed for {symbol}: {e}") from e
        bars: list[Bar] = []
        for ts, row in hist.iterrows():
            day = ts.date()
            if day < start or day > end:
                continue
            b = _bar(symbol, day, row["Open"], row["High"], row["Low"], row["Close"], row["Volume"])
            if b:
                bars.append(b)
        return sorted(bars, key=lambda b: b.session_date)


class StooqProvider(HistoricalMarketDataProvider):
    name = "stooq"
    base_url = "https://stooq.com/q/d/l/"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30)

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        params = {
            "s": f"{symbol.lower()}.us",
            "i": "d",
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }
        try:
            r = self._client.get(self.base_url, params=params)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderFetchError(f"stooq fetch failed for {symbol}: {e}") from e
        text = r.text
        if "Exceeded the daily hits limit" in text or not text.strip():
            raise ProviderFetchError(
                f"stooq returned no data for {symbol} (limit or unknown symbol)"
            )
        bars: list[Bar] = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                day = datetime.strptime(row["Date"], "%Y-%m-%d").date()
            except (KeyError, ValueError):
                continue
            b = _bar(
                symbol,
                day,
                row.get("Open"),
                row.get("High"),
                row.get("Low"),
                row.get("Close"),
                row.get("Volume"),
            )
            if b and start <= day <= end:
                bars.append(b)
        return sorted(bars, key=lambda b: b.session_date)


class PolygonProvider(HistoricalMarketDataProvider):
    name = "polygon"
    base_url = "https://api.polygon.io"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ProviderConfigurationError("HISTORY_PROVIDER=polygon requires POLYGON_API_KEY")
        self._key = api_key
        self._client = client or httpx.Client(timeout=30)

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        url = f"{self.base_url}/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        params: dict[str, str | int] = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self._key,
        }
        try:
            r = self._client.get(url, params=params)
            r.raise_for_status()
            payload = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderFetchError(
                f"polygon fetch failed for {symbol}: {type(e).__name__}"
            ) from e
        bars: list[Bar] = []
        for item in payload.get("results", []) or []:
            day = datetime.fromtimestamp(
                item["t"] / 1000, tz=datetime.now().astimezone().tzinfo
            ).date()
            b = _bar(
                symbol,
                day,
                item.get("o"),
                item.get("h"),
                item.get("l"),
                item.get("c"),
                item.get("v"),
            )
            if b and start <= day <= end:
                bars.append(b)
        return bars


class AlpacaProvider(HistoricalMarketDataProvider):
    name = "alpaca"
    base_url = "https://data.alpaca.markets"

    def __init__(self, api_key: str, api_secret: str, client: httpx.Client | None = None) -> None:
        if not api_key or not api_secret:
            raise ProviderConfigurationError(
                "HISTORY_PROVIDER=alpaca requires ALPACA_API_KEY and ALPACA_API_SECRET"
            )
        self._client = client or httpx.Client(
            timeout=30, headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
        )

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        bars: list[Bar] = []
        page_token: str | None = None
        while True:
            params: dict[str, str | int] = {
                "symbols": symbol.upper(),
                "timeframe": "1Day",
                "start": f"{start.isoformat()}T00:00:00Z",
                "end": f"{end.isoformat()}T23:59:59Z",
                "adjustment": "split",
                "feed": "iex",
                "limit": 10000,
            }
            if page_token:
                params["page_token"] = page_token
            try:
                r = self._client.get(f"{self.base_url}/v2/stocks/bars", params=params)
                r.raise_for_status()
                payload = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise ProviderFetchError(
                    f"alpaca fetch failed for {symbol}: {type(e).__name__}"
                ) from e
            for item in (payload.get("bars") or {}).get(symbol.upper(), []):
                day = datetime.fromisoformat(item["t"].replace("Z", "+00:00")).date()
                b = _bar(
                    symbol,
                    day,
                    item.get("o"),
                    item.get("h"),
                    item.get("l"),
                    item.get("c"),
                    item.get("v"),
                )
                if b and start <= day <= end:
                    bars.append(b)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return sorted(bars, key=lambda b: b.session_date)


class TwelveDataProvider(HistoricalMarketDataProvider):
    name = "twelvedata"
    base_url = "https://api.twelvedata.com"

    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        if not api_key:
            raise ProviderConfigurationError(
                "HISTORY_PROVIDER=twelvedata requires TWELVEDATA_API_KEY"
            )
        self._key = api_key
        self._client = client or httpx.Client(timeout=30)

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        params: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "interval": "1day",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "outputsize": 5000,
            "order": "ASC",
            "apikey": self._key,
        }
        try:
            r = self._client.get(f"{self.base_url}/time_series", params=params)
            r.raise_for_status()
            payload = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderFetchError(
                f"twelvedata fetch failed for {symbol}: {type(e).__name__}"
            ) from e
        if payload.get("status") == "error":
            raise ProviderFetchError(f"twelvedata error for {symbol}: {payload.get('message')}")
        bars: list[Bar] = []
        for item in payload.get("values", []) or []:
            day = datetime.strptime(item["datetime"][:10], "%Y-%m-%d").date()
            b = _bar(
                symbol,
                day,
                item.get("open"),
                item.get("high"),
                item.get("low"),
                item.get("close"),
                item.get("volume"),
            )
            if b and start <= day <= end:
                bars.append(b)
        return sorted(bars, key=lambda b: b.session_date)


def build_provider(name: str, settings: object) -> HistoricalMarketDataProvider:
    """Factory keyed by HISTORY_PROVIDER. Keyed providers fail loudly without credentials."""
    from zipline_engine.config import Settings

    assert isinstance(settings, Settings)
    if name == "yfinance":
        return YFinanceProvider()
    if name == "stooq":
        return StooqProvider()
    if name == "polygon":
        return PolygonProvider(settings.polygon_api_key.get_secret_value())
    if name == "alpaca":
        return AlpacaProvider(
            settings.alpaca_api_key.get_secret_value(),
            settings.alpaca_api_secret.get_secret_value(),
        )
    if name == "twelvedata":
        return TwelveDataProvider(settings.twelvedata_api_key.get_secret_value())
    raise ProviderConfigurationError(f"unknown HISTORY_PROVIDER {name!r}")
