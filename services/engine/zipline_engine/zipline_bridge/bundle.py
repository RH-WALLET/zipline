"""A zipline-reloaded data bundle built from the engine's cached historical bars.

The same UNDERLYING equity bars the live cycle uses are written into a Zipline bundle so
every strategy can be backtested with the real Zipline simulator (``zl backtest``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from zipline_engine.config import get_settings
from zipline_engine.db.base import session_scope
from zipline_engine.db.models import HistoricalBar

log = logging.getLogger(__name__)

BUNDLE_NAME = "zipline-rh-history"
CALENDAR = "XNYS"


def zipline_root() -> Path:
    root = Path(get_settings().history_cache_dir).resolve() / "zipline"
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("ZIPLINE_ROOT", str(root))
    return Path(os.environ["ZIPLINE_ROOT"])


def load_bars(provider: str) -> pd.DataFrame:
    with session_scope() as session:
        rows = (
            session.execute(
                select(HistoricalBar)
                .where(HistoricalBar.provider == provider)
                .order_by(HistoricalBar.symbol, HistoricalBar.session_date)
            )
            .scalars()
            .all()
        )
        return pd.DataFrame(
            {
                "symbol": [r.symbol for r in rows],
                "date": [pd.Timestamp(r.session_date) for r in rows],
                "open": [float(r.open) for r in rows],
                "high": [float(r.high) for r in rows],
                "low": [float(r.low) for r in rows],
                "close": [float(r.close) for r in rows],
                "volume": [float(r.volume) for r in rows],
            }
        )


def make_ingest(provider: str):  # type: ignore[no-untyped-def]
    def ingest(
        environ,
        asset_db_writer,
        minute_bar_writer,
        daily_bar_writer,
        adjustment_writer,
        calendar,
        start_session,
        end_session,
        cache,
        show_progress,
        output_dir,
    ):  # type: ignore[no-untyped-def]
        bars = load_bars(provider)
        if bars.empty:
            raise RuntimeError("no cached historical bars; run `zl load-history` first")
        symbols = sorted(bars["symbol"].unique())
        sessions = calendar.sessions_in_range(start_session, end_session)
        meta_rows = []

        def frames() -> Iterator[tuple[int, pd.DataFrame]]:
            for sid, sym in enumerate(symbols):
                df = (
                    bars[bars["symbol"] == sym]
                    .set_index("date")[["open", "high", "low", "close", "volume"]]
                    .sort_index()
                )
                df = df[~df.index.duplicated(keep="last")]
                first, last = df.index[0], df.index[-1]
                idx = sessions[(sessions >= first) & (sessions <= last)]
                df = df.reindex(idx)
                df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].ffill()
                df["volume"] = df["volume"].fillna(0.0)
                meta_rows.append(
                    {
                        "sid": sid,
                        "symbol": sym,
                        "asset_name": sym,
                        "start_date": first,
                        "end_date": last,
                        "first_traded": first,
                        "auto_close_date": last + pd.Timedelta(days=1),
                        "exchange": CALENDAR,
                    }
                )
                yield sid, df

        daily_bar_writer.write(frames(), show_progress=show_progress)
        equities = pd.DataFrame(meta_rows).set_index("sid")
        exchanges = pd.DataFrame(
            {"exchange": [CALENDAR], "canonical_name": [CALENDAR], "country_code": ["US"]}
        )
        asset_db_writer.write(equities=equities, exchanges=exchanges)
        adjustment_writer.write()
        log.info("ingested %d symbols into bundle (%s)", len(symbols), provider)

    return ingest


def register_bundle(name: str = BUNDLE_NAME, provider: str | None = None) -> None:
    from zipline.data import bundles

    provider = provider or get_settings().history_provider
    zipline_root()
    if name in bundles.bundles:
        return
    bundles.register(name, make_ingest(provider), calendar_name=CALENDAR)


def ingest(name: str = BUNDLE_NAME) -> Path:
    from zipline.data import bundles

    register_bundle(name)
    bundles.ingest(name, show_progress=False)
    return zipline_root() / "data" / name


def is_ingested(name: str = BUNDLE_NAME) -> bool:
    return (zipline_root() / "data" / name).exists()
