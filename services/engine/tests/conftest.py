"""Shared fixtures. Pure-logic tests need no database; DB tests use TEST_DATABASE_URL (Postgres)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

os.environ.setdefault("LIVE_TRADING", "false")
os.environ.setdefault("TREASURY_MODE", "simulated")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("EXECUTOR_PRIVATE_KEY", "")
os.environ.setdefault("ETH_USD_PRICE_SOURCE", "none")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://zipline:zipline@localhost:5433/zipline_test"
)

from zipline_engine.accounting.books import Book  # noqa: E402
from zipline_engine.core.calendar import sessions_between  # noqa: E402
from zipline_engine.marketdata.base import Bar  # noqa: E402
from zipline_engine.marketdata.service import Panel, panel_from_bars  # noqa: E402

SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "XOM"]


def synthetic_bars(
    symbols: list[str] = SYMBOLS, end: date = date(2026, 9, 17), n: int = 320, seed: int = 7
) -> list[Bar]:
    """Deterministic synthetic daily bars for tests (never used at runtime)."""
    rng = np.random.default_rng(seed)
    sessions = sessions_between(end - timedelta(days=int(n * 1.6)), end)[-n:]
    bars: list[Bar] = []
    for i, sym in enumerate(sorted(symbols)):
        px = 100.0 * (1 + i * 0.5)
        drift = 0.0004 * (1 + i % 3)
        for day in sessions:
            ret = drift + rng.normal(0, 0.012)
            px = max(px * (1 + ret), 1.0)
            hi, lo = px * (1 + abs(rng.normal(0, 0.004))), px * (1 - abs(rng.normal(0, 0.004)))
            bars.append(
                Bar(
                    sym,
                    day,
                    Decimal(repr(round(px * 0.999, 4))),
                    Decimal(repr(round(hi, 4))),
                    Decimal(repr(round(lo, 4))),
                    Decimal(repr(round(px, 4))),
                    Decimal(1_000_000),
                )
            )
    return bars


@pytest.fixture(scope="session")
def panel() -> Panel:
    return panel_from_bars(synthetic_bars(), provider="test")


@pytest.fixture
def prices() -> dict[str, Decimal]:
    return {
        s: Decimal(p)
        for s, p in {
            "AAPL": "200",
            "MSFT": "400",
            "NVDA": "150",
            "SPY": "600",
            "QQQ": "500",
            "XOM": "120",
        }.items()
    }


@pytest.fixture
def book() -> Book:
    b = Book(code="TEST")
    b.add_capital(Decimal("1000"))
    b.mark({})
    return b


@pytest.fixture(scope="session")
def db_engine():  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine, text

    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, future=True)
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:  # pragma: no cover
        pytest.skip(f"test database unavailable at {url}: {e}")
    from zipline_engine.db.models import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[object]:  # type: ignore[no-untyped-def]
    """A fresh schema per test (tables truncated)."""
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from zipline_engine.db.models import Base

    with db_engine.begin() as conn:
        tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    from zipline_engine.db import base as dbbase

    dbbase.reset_engine_cache()
    session = Session(bind=db_engine, expire_on_commit=False, autoflush=False)
    try:
        yield session
        session.rollback()
    finally:
        session.close()
