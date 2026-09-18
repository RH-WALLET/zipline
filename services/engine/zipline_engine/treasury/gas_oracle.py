"""ETH/USD for reporting gas cost in dollars. Never used for trading decisions."""

from __future__ import annotations

import logging
import time
from decimal import Decimal

import httpx

from zipline_engine.core.money import D

log = logging.getLogger(__name__)


class GasPriceOracle:
    def __init__(
        self, source: str, chain: object | None = None, chainlink_feed: str = "", ttl_sec: int = 300
    ) -> None:
        self.source = source
        self.chain = chain
        self.feed = chainlink_feed
        self.ttl = ttl_sec
        self._cached: tuple[float, Decimal | None] = (0.0, None)

    def eth_usd(self) -> Decimal | None:
        ts, val = self._cached
        if time.time() - ts < self.ttl:
            return val
        val = self._fetch()
        self._cached = (time.time(), val)
        return val

    def _fetch(self) -> Decimal | None:
        try:
            if self.source == "coinbase":
                r = httpx.get("https://api.coinbase.com/v2/prices/ETH-USD/spot", timeout=10)
                r.raise_for_status()
                return D(r.json()["data"]["amount"])
            if self.source == "chainlink" and self.chain is not None and self.feed:
                price, _ = self.chain.chainlink_price(self.feed)  # type: ignore[attr-defined]
                return price
        except Exception as e:
            log.warning("ETH/USD price unavailable (%s): %s", self.source, e)
        return None
