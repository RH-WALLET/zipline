"""Live valuation prices for Stock Tokens.

Reference price = Robinhood underlying mid (bid+ask)/2 × current multiplier = USD per raw
token. Used for internal crosses, dry-run fills, valuation, and as the benchmark against
which executable quotes are checked for slippage.

Fallback order when the live API is unavailable: latest stored PriceSnapshot, then the last
historical close (flagged ``source="last_close"`` and ``stale=True``; never used to execute).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.config import Settings
from zipline_engine.core.money import D
from zipline_engine.core.multiplier import token_price
from zipline_engine.db.models import Asset, HistoricalBar, PriceSnapshot
from zipline_engine.robinhood.client import RHPrice, RobinhoodStockTokenClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefPrice:
    symbol: str
    asset_id: int
    underlying_bid: Decimal
    underlying_ask: Decimal
    underlying_mid: Decimal
    multiplier: Decimal
    generated_at: datetime | None
    fetched_at: datetime
    source: str
    is_halted: bool
    stale: bool

    @property
    def token_mid(self) -> Decimal:
        return token_price(self.underlying_mid, self.multiplier)

    @property
    def token_bid(self) -> Decimal:
        return token_price(self.underlying_bid, self.multiplier)

    @property
    def token_ask(self) -> Decimal:
        return token_price(self.underlying_ask, self.multiplier)

    @property
    def spread_bps(self) -> Decimal:
        if self.underlying_mid == 0:
            return Decimal(0)
        return (self.underlying_ask - self.underlying_bid) / self.underlying_mid * Decimal(10_000)


class LivePricingService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        rh_client: RobinhoodStockTokenClient | None,
        snapshot_max_age: timedelta = timedelta(hours=36),
    ) -> None:
        self.session = session
        self.settings = settings
        self.rh = rh_client
        self.snapshot_max_age = snapshot_max_age

    def snapshot(self, assets: list[Asset]) -> dict[str, RefPrice]:
        """Fetch live prices for ``assets``; persist snapshots; fall back per asset."""
        now = datetime.now(UTC)
        out: dict[str, RefPrice] = {}
        live: dict[str, RHPrice | Exception] = {}
        if self.rh is not None:
            live = self.rh.get_prices([a.symbol for a in assets])
        for asset in assets:
            p = live.get(asset.symbol)
            if isinstance(p, RHPrice) and p.valid:
                assert p.bid is not None and p.ask is not None
                snap = PriceSnapshot(
                    asset_id=asset.id,
                    source="robinhood_api",
                    bid=p.bid,
                    ask=p.ask,
                    mid=p.mid,
                    currency=p.currency,
                    daily_volume=p.dailyTradingVolume,
                    is_halted=p.isTradingHalt,
                    generated_at=p.generatedAt,
                    fetched_at=now,
                )
                self.session.add(snap)
                stale = False
                if p.generatedAt is not None:
                    age = (now - p.generatedAt.astimezone(UTC)).total_seconds()
                    stale = age > self.settings.price_staleness_sec
                out[asset.symbol] = RefPrice(
                    symbol=asset.symbol,
                    asset_id=asset.id,
                    underlying_bid=p.bid,
                    underlying_ask=p.ask,
                    underlying_mid=D(p.mid),
                    multiplier=asset.current_multiplier or Decimal(1),
                    generated_at=p.generatedAt,
                    fetched_at=now,
                    source="robinhood_api",
                    is_halted=p.isTradingHalt,
                    stale=stale,
                )
            else:
                fallback = self._fallback(asset, now)
                if fallback is not None:
                    out[asset.symbol] = fallback
        self.session.flush()
        return out

    def latest(self, assets: list[Asset]) -> dict[str, RefPrice]:
        """Best available price per asset WITHOUT calling the network."""
        now = datetime.now(UTC)
        out: dict[str, RefPrice] = {}
        for asset in assets:
            fb = self._fallback(asset, now)
            if fb is not None:
                out[asset.symbol] = fb
        return out

    def _fallback(self, asset: Asset, now: datetime) -> RefPrice | None:
        snap = self.session.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.asset_id == asset.id, PriceSnapshot.mid.is_not(None))
            .order_by(PriceSnapshot.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        mult = asset.current_multiplier or Decimal(1)
        if (
            snap is not None
            and snap.mid
            and (now - snap.fetched_at.astimezone(UTC)) <= self.snapshot_max_age
        ):
            return RefPrice(
                symbol=asset.symbol,
                asset_id=asset.id,
                underlying_bid=D(snap.bid),
                underlying_ask=D(snap.ask),
                underlying_mid=D(snap.mid),
                multiplier=mult,
                generated_at=snap.generated_at,
                fetched_at=snap.fetched_at,
                source="cached_snapshot",
                is_halted=snap.is_halted,
                stale=True,
            )
        bar = self.session.execute(
            select(HistoricalBar)
            .where(HistoricalBar.symbol == asset.symbol)
            .order_by(HistoricalBar.session_date.desc())
            .limit(1)
        ).scalar_one_or_none()
        if bar is not None:
            close = D(bar.close)
            return RefPrice(
                symbol=asset.symbol,
                asset_id=asset.id,
                underlying_bid=close,
                underlying_ask=close,
                underlying_mid=close,
                multiplier=mult,
                generated_at=datetime.combine(bar.session_date, datetime.min.time(), tzinfo=UTC),
                fetched_at=now,
                source="last_close",
                is_halted=asset.is_halted,
                stale=True,
            )
        return None
