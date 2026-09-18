"""ORM rows -> JSON-safe dicts. Decimals become strings so nothing is rounded in transit."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from zipline_engine.db.models import (
    Asset,
    BlockchainTransaction,
    Cycle,
    ExecutionOrder,
    ExecutionQuote,
    FundingEvent,
    InternalCross,
    PortfolioSnapshot,
    PriceSnapshot,
    ReconciliationEvent,
    StrategySignal,
    SystemEvent,
    TreasurySnapshot,
    VirtualFill,
    WithdrawalEvent,
)

JS_SAFE_INT = 2**53 - 1


def j(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and abs(value) > JS_SAFE_INT:
        return str(value)  # 63-bit seeds must survive JSON -> JavaScript intact
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text or "0"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: j(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [j(v) for v in value]
    return value


def row(obj: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    exclude = exclude or set()
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        out[col.name] = j(getattr(obj, col.name))
    return out


def asset(
    a: Asset, price: PriceSnapshot | None = None, chain_id: int | None = None
) -> dict[str, Any]:
    d = row(a)
    d["deployments"] = [row(dep) for dep in a.deployments]
    d["deployment"] = next(
        (row(dep) for dep in a.deployments if chain_id is None or dep.chain_id == chain_id), None
    )
    d["hold_only"] = "hold_only" in (a.eligibility_reasons or [])
    d["price"] = row(price) if price else None
    return d


def order(o: ExecutionOrder, symbol: str | None, explorer: str) -> dict[str, Any]:
    d = row(o)
    d["symbol"] = symbol
    d["quotes"] = [quote(q) for q in o.quotes]
    d["transactions"] = [transaction(t, explorer) for t in o.transactions]
    d["is_real"] = o.mode == "LIVE"
    return d


def quote(q: ExecutionQuote) -> dict[str, Any]:
    return row(q)


def transaction(t: BlockchainTransaction, explorer: str) -> dict[str, Any]:
    d = row(t)
    d["explorer_url"] = f"{explorer.rstrip('/')}/tx/{t.tx_hash}"
    return d


def signal(s: StrategySignal, symbol: str | None, strategy_code: str | None) -> dict[str, Any]:
    d = row(s)
    d["symbol"] = symbol
    d["strategy"] = strategy_code
    return d


def fill(f: VirtualFill, symbol: str | None, strategy_code: str | None) -> dict[str, Any]:
    d = row(f)
    d["symbol"] = symbol
    d["strategy"] = strategy_code
    return d


def cross(
    c: InternalCross, symbol: str | None, buyer: str | None, seller: str | None
) -> dict[str, Any]:
    d = row(c)
    d["symbol"] = symbol
    d["buyer"] = buyer
    d["seller"] = seller
    return d


def treasury_snapshot(s: TreasurySnapshot) -> dict[str, Any]:
    return row(s)


def portfolio_snapshot(s: PortfolioSnapshot) -> dict[str, Any]:
    return row(s)


def funding(f: FundingEvent, explorer: str) -> dict[str, Any]:
    d = row(f)
    d["explorer_url"] = f"{explorer.rstrip('/')}/tx/{f.tx_hash}" if f.tx_hash else None
    return d


def withdrawal(w: WithdrawalEvent, explorer: str) -> dict[str, Any]:
    d = row(w)
    d["explorer_url"] = f"{explorer.rstrip('/')}/tx/{w.tx_hash}" if w.tx_hash else None
    return d


def reconciliation(r: ReconciliationEvent) -> dict[str, Any]:
    return row(r)


def event(e: SystemEvent) -> dict[str, Any]:
    return row(e)


def cycle(c: Cycle) -> dict[str, Any]:
    return row(c)
