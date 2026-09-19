"""Live quote board: Robinhood's public bid/ask for every tracked Stock Token.

A display feed for the terminal page. It is read-only — nothing here is persisted or used
for valuation (valuations use the scheduled PriceSnapshot rows) — and it is cached for a few
seconds server-side so any number of viewers costs Robinhood's API at most one round of
requests per TTL. When the live fetch fails for an asset, the latest stored snapshot is
returned for it and marked ``source="cached_snapshot"``; nothing is estimated.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.api import serializers as ser
from zipline_engine.api.deps import db, settings
from zipline_engine.config import Settings
from zipline_engine.core.money import D
from zipline_engine.core.multiplier import token_price
from zipline_engine.db.models import Asset, PriceSnapshot
from zipline_engine.robinhood.client import RHPrice, RobinhoodStockTokenClient

router = APIRouter()

QUOTE_TTL_SEC = 20.0
_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def _default_client(cfg: Settings) -> Any:
    return RobinhoodStockTokenClient(cfg.rh_stock_token_api_url, timeout=8.0)


# Tests replace this with a factory returning a fake; production uses the real client.
client_factory: Callable[[Settings], Any] = _default_client


def _fetch_live(rh: Any, symbols: list[str]) -> dict[str, RHPrice | Exception]:
    out: dict[str, RHPrice | Exception] = {}

    def one(sym: str) -> tuple[str, RHPrice | Exception]:
        try:
            return sym, rh.get_price(sym)
        except Exception as e:  # noqa: BLE001 — per-symbol failure falls back below
            return sym, e

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(symbols)))) as pool:
        for sym, res in pool.map(one, symbols):
            out[sym] = res
    return out


def _spread_bps(bid: Decimal, ask: Decimal, mid: Decimal) -> Decimal | None:
    if mid <= 0:
        return None
    return (ask - bid) / mid * Decimal(10_000)


def _row(
    a: Asset, live: RHPrice | Exception | None, snap: PriceSnapshot | None, now: datetime
) -> dict[str, Any]:
    mult = a.current_multiplier or Decimal(1)
    base: dict[str, Any] = {
        "symbol": a.symbol,
        "name": a.name,
        "multiplier": mult,
        "eligible": a.eligible,
        "hold_only": "hold_only" in (a.eligibility_reasons or []),
        "status": a.status,
    }
    if isinstance(live, RHPrice) and live.valid:
        assert live.bid is not None and live.ask is not None and live.mid is not None
        bid, ask, mid = live.bid, live.ask, D(live.mid)
        base.update(
            source="robinhood_api",
            is_halted=live.isTradingHalt,
            daily_volume=live.dailyTradingVolume,
            generated_at=live.generatedAt,
            fetched_at=now,
        )
    elif snap is not None and snap.mid:
        bid, ask, mid = D(snap.bid), D(snap.ask), D(snap.mid)
        base.update(
            source="cached_snapshot",
            is_halted=snap.is_halted,
            daily_volume=snap.daily_volume,
            generated_at=snap.generated_at,
            fetched_at=snap.fetched_at,
            error=str(live) if isinstance(live, Exception) else None,
        )
    else:
        base.update(
            source=None,
            bid=None,
            ask=None,
            mid=None,
            spread_bps=None,
            token_bid=None,
            token_ask=None,
            token_mid=None,
            is_halted=a.is_halted,
            daily_volume=None,
            generated_at=None,
            fetched_at=None,
            error=str(live) if isinstance(live, Exception) else "no price",
        )
        return {k: ser.j(v) for k, v in base.items()}
    base.update(
        bid=bid,
        ask=ask,
        mid=mid,
        spread_bps=_spread_bps(bid, ask, mid),
        token_bid=token_price(bid, mult),
        token_ask=token_price(ask, mult),
        token_mid=token_price(mid, mult),
    )
    base.setdefault("error", None)
    return {k: ser.j(v) for k, v in base.items()}


def _build(session: Session, cfg: Settings) -> dict[str, Any]:
    now = datetime.now(UTC)
    assets = (
        session.execute(select(Asset).where(Asset.in_allowlist.is_(True)).order_by(Asset.symbol))
        .scalars()
        .all()
    )
    symbols = [a.symbol for a in assets]
    live: dict[str, RHPrice | Exception] = {}
    api_error: str | None = None
    try:
        live = _fetch_live(client_factory(cfg), symbols) if symbols else {}
    except Exception as e:  # noqa: BLE001 — whole feed down: fall back to snapshots
        api_error = f"{type(e).__name__}: {e}"
    rows: list[dict[str, Any]] = []
    for a in assets:
        snap = session.execute(
            select(PriceSnapshot)
            .where(PriceSnapshot.asset_id == a.id, PriceSnapshot.mid.is_not(None))
            .order_by(PriceSnapshot.fetched_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        rows.append(_row(a, live.get(a.symbol), snap, now))
    live_count = sum(1 for r in rows if r["source"] == "robinhood_api")
    return {
        "fetched_at": now.isoformat(),
        "ttl_sec": QUOTE_TTL_SEC,
        "source": f"GET {cfg.rh_stock_token_api_url}/prices/{{symbol}}",
        "live": live_count,
        "cached": len(rows) - live_count,
        "error": api_error,
        "note": (
            "Underlying-equity bid/ask from Robinhood's public API; token values are price × "
            "ERC-8056 multiplier. Display feed only — valuations use the scheduled snapshots."
        ),
        "quotes": rows,
    }


@router.get("/quotes")
async def quotes(
    session: Session = Depends(db), cfg: Settings = Depends(settings)
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    now = loop.time()
    with _lock:
        cached = _cache["payload"]
        if cached is not None and now - _cache["at"] < QUOTE_TTL_SEC:
            return {**cached, "age_sec": round(now - _cache["at"], 1)}
    payload = await asyncio.to_thread(_build, session, cfg)
    with _lock:
        _cache["payload"] = payload
        _cache["at"] = loop.time()
    return {**payload, "age_sec": 0.0}
