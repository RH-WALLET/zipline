"""Persistent models.

Quantities of Stock Tokens are stored in *raw token units* (what ``balanceOf`` returns,
scaled by 1e18) as ``Numeric(40, 18)``. Valuation applies the current ERC-8056 multiplier
and the underlying per-share price at read time, so corporate actions never create or
destroy PnL. Money is USD (the cash token is a USD stablecoin) as ``Numeric(40, 18)``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = Numeric(40, 18)
Qty = Numeric(40, 18)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


# ----------------------------------------------------------------------------- assets


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    rh_asset_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="ASSET_STATUS_UNSPECIFIED")
    current_multiplier: Mapped[Decimal] = mapped_column(Qty, default=Decimal("1"))
    pending_multiplier: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    pending_multiplier_effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fractional_tradability: Mapped[bool] = mapped_column(Boolean, default=False)
    all_day_tradability: Mapped[bool] = mapped_column(Boolean, default=False)
    extended_hours_fractional_tradability: Mapped[bool] = mapped_column(Boolean, default=False)
    is_halted: Mapped[bool] = mapped_column(Boolean, default=False)
    in_allowlist: Mapped[bool] = mapped_column(Boolean, default=False)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    eligibility_reasons: Mapped[list[Any]] = mapped_column(JSON, default=list)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    deployments: Mapped[list[AssetDeployment]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class AssetDeployment(Base):
    __tablename__ = "asset_deployments"
    __table_args__ = (UniqueConstraint("asset_id", "chain_id", name="uq_asset_chain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    chain_id: Mapped[int] = mapped_column(Integer)
    contract_address: Mapped[str] = mapped_column(String(42))
    decimals: Mapped[int] = mapped_column(Integer, default=18)
    verified_onchain: Mapped[bool] = mapped_column(Boolean, default=False)
    onchain_multiplier: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    asset: Mapped[Asset] = relationship(back_populates="deployments")


class PriceSnapshot(Base):
    """Live Robinhood Stock Token pricing (underlying per-share bid/ask, NOT multiplier-adjusted)."""

    __tablename__ = "price_snapshots"
    __table_args__ = (Index("ix_price_asset_fetched", "asset_id", "fetched_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    source: Mapped[str] = mapped_column(String(32), default="robinhood_api")
    bid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    ask: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    mid: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    daily_volume: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    is_halted: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HistoricalBar(Base):
    """Daily OHLCV of the UNDERLYING equity from a historical data provider (never chain data)."""

    __tablename__ = "historical_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "provider", "session_date", name="uq_bar_symbol_provider_date"),
        Index("ix_bars_symbol_date", "symbol", "session_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    session_date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal] = mapped_column(Money)
    high: Mapped[Decimal] = mapped_column(Money)
    low: Mapped[Decimal] = mapped_column(Money)
    close: Mapped[Decimal] = mapped_column(Money)
    volume: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ------------------------------------------------------------------------- strategies


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    status_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list[StrategyVersion]] = relationship(back_populates="strategy")
    state: Mapped[StrategyState | None] = relationship(back_populates="strategy", uselist=False)
    positions: Mapped[list[StrategyPosition]] = relationship(back_populates="strategy")


class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_id", "version_hash", name="uq_strategy_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    version_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    strategy: Mapped[Strategy] = relationship(back_populates="versions")


class StrategyAllocation(Base):
    """Target capital weight of a sleeve. History is kept; the row with active=True is current."""

    __tablename__ = "strategy_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    weight_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    policy: Mapped[str] = mapped_column(String(32), default="EQUAL_WEIGHT")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class StrategyState(Base):
    """Virtual sleeve accounting. Sum over sleeves reconciles to the treasury."""

    __tablename__ = "strategy_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), unique=True)
    virtual_cash: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    allocated_capital: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    current_nav: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    peak_nav: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    max_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    current_drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    cumulative_turnover: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    signals_count: Mapped[int] = mapped_column(Integer, default=0)
    fills_count: Mapped[int] = mapped_column(Integer, default=0)
    twr_index: Mapped[Decimal] = mapped_column(Money, default=Decimal(1))
    last_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_rebalance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inception_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    strategy: Mapped[Strategy] = relationship(back_populates="state")


class StrategyPosition(Base):
    __tablename__ = "strategy_positions"
    __table_args__ = (UniqueConstraint("strategy_id", "asset_id", name="uq_strategy_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    cost_basis: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    last_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    market_value: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    strategy: Mapped[Strategy] = relationship(back_populates="positions")
    asset: Mapped[Asset] = relationship()


class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nav_at_start: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class StrategySignal(Base):
    __tablename__ = "strategy_signals"
    __table_args__ = (Index("ix_signals_strategy_created", "strategy_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"), index=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("assets.id"), nullable=True)
    session_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(32))
    value: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    target_weight: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    previous_weight: Mapped[Decimal] = mapped_column(Numeric(14, 8), default=Decimal(0))
    version_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InternalCross(Base):
    """Two sleeves exchanged a position inside the treasury. No blockchain transaction."""

    __tablename__ = "internal_crosses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("cycles.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    buyer_strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    seller_strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    price: Mapped[Decimal] = mapped_column(Money)
    notional: Mapped[Decimal] = mapped_column(Money)
    reference_price_source: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionOrder(Base):
    """Net external trade for one asset in one cycle. May be dry-run or live."""

    __tablename__ = "execution_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    local_id: Mapped[str] = mapped_column(String(32), unique=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("cycles.id"), nullable=True, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    side: Mapped[str] = mapped_column(String(4))
    mode: Mapped[str] = mapped_column(String(8))
    adapter: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    requested_quantity: Mapped[Decimal] = mapped_column(Qty)
    requested_notional: Mapped[Decimal] = mapped_column(Money)
    quoted_quantity: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    quoted_notional: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    executed_quantity: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    executed_notional: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    reference_price: Mapped[Decimal] = mapped_column(Money)
    expected_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    effective_price: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    slippage_bps: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    price_impact_bps: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    gas_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_cost_eth: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    gas_cost_usd: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    contributions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    asset: Mapped[Asset] = relationship()
    quotes: Mapped[list[ExecutionQuote]] = relationship(back_populates="order")
    transactions: Mapped[list[BlockchainTransaction]] = relationship(back_populates="order")


class ExecutionQuote(Base):
    __tablename__ = "execution_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("execution_orders.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    sell_token: Mapped[str] = mapped_column(String(42))
    buy_token: Mapped[str] = mapped_column(String(42))
    sell_amount: Mapped[Decimal] = mapped_column(Qty)
    buy_amount: Mapped[Decimal] = mapped_column(Qty)
    min_buy_amount: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    price: Mapped[Decimal] = mapped_column(Money)
    price_impact_bps: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    gas_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_price_wei: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    allowance_spender: Mapped[str | None] = mapped_column(String(42), nullable=True)
    allowance_required: Mapped[bool] = mapped_column(Boolean, default=False)
    liquidity_available: Mapped[bool] = mapped_column(Boolean, default=True)
    route: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="VALID")
    quoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped[ExecutionOrder] = relationship(back_populates="quotes")


class BlockchainTransaction(Base):
    """A REAL transaction broadcast to Robinhood Chain. Never created in dry-run mode."""

    __tablename__ = "blockchain_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_orders.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    chain_id: Mapped[int] = mapped_column(Integer)
    tx_hash: Mapped[str] = mapped_column(String(66), unique=True)
    from_address: Mapped[str] = mapped_column(String(42))
    to_address: Mapped[str] = mapped_column(String(42))
    nonce: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gas_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    effective_gas_price_wei: Mapped[Decimal | None] = mapped_column(Qty, nullable=True)
    gas_cost_eth: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    gas_cost_usd: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order: Mapped[ExecutionOrder | None] = relationship(back_populates="transactions")


class VirtualFill(Base):
    """Change to a sleeve's virtual position and the mechanism that caused it."""

    __tablename__ = "virtual_fills"
    __table_args__ = (Index("ix_fills_strategy_created", "strategy_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("cycles.id"), nullable=True, index=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    side: Mapped[str] = mapped_column(String(4))
    kind: Mapped[str] = mapped_column(String(24))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    price: Mapped[Decimal] = mapped_column(Money)
    notional: Mapped[Decimal] = mapped_column(Money)
    realized_pnl: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    internal_cross_id: Mapped[int | None] = mapped_column(
        ForeignKey("internal_crosses.id"), nullable=True
    )
    execution_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_orders.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------- treasury


class TreasurySnapshot(Base):
    __tablename__ = "treasury_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(16))
    wallet_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    nav: Mapped[Decimal] = mapped_column(Money)
    cash_balance: Mapped[Decimal] = mapped_column(Money)
    positions_value: Mapped[Decimal] = mapped_column(Money)
    deployable_capital: Mapped[Decimal] = mapped_column(Money)
    reserved_cash: Mapped[Decimal] = mapped_column(Money)
    gas_balance_eth: Mapped[Decimal] = mapped_column(Money)
    gas_balance_usd: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    realized_pnl: Mapped[Decimal] = mapped_column(Money)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Money)
    cumulative_gas_eth: Mapped[Decimal] = mapped_column(Money)
    cumulative_gas_usd: Mapped[Decimal] = mapped_column(Money)
    base_capital: Mapped[Decimal] = mapped_column(Money)
    contributions_total: Mapped[Decimal] = mapped_column(Money)
    withdrawals_total: Mapped[Decimal] = mapped_column(Money)
    twr_index: Mapped[Decimal] = mapped_column(Money, default=Decimal(1))
    positions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PortfolioSnapshot(Base):
    """Per-sleeve valuation point (equity curve)."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("ix_psnap_strategy_taken", "strategy_id", "taken_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    nav: Mapped[Decimal] = mapped_column(Money)
    cash: Mapped[Decimal] = mapped_column(Money)
    positions_value: Mapped[Decimal] = mapped_column(Money)
    allocated_capital: Mapped[Decimal] = mapped_column(Money)
    realized_pnl: Mapped[Decimal] = mapped_column(Money)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Money)
    drawdown_pct: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    twr_index: Mapped[Decimal] = mapped_column(Money, default=Decimal(1))
    positions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class FundingEvent(Base):
    __tablename__ = "funding_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Money)
    asset_symbol: Mapped[str] = mapped_column(String(16))
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    from_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    allocated: Mapped[bool] = mapped_column(Boolean, default=False)
    allocation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class WithdrawalEvent(Base):
    __tablename__ = "withdrawal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    asset_symbol: Mapped[str] = mapped_column(String(16))
    to_address: Mapped[str | None] = mapped_column(String(42), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="RECORDED")
    requested_by: Mapped[str] = mapped_column(String(64), default="operator")
    deallocation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ReconciliationEvent(Base):
    __tablename__ = "reconciliation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    tolerance_bps: Mapped[int] = mapped_column(Integer)
    max_break_bps: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal(0))
    cash_break: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    position_breaks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    triggered_pause: Mapped[bool] = mapped_column(Boolean, default=False)


class SystemEvent(Base):
    __tablename__ = "system_events"
    __table_args__ = (Index("ix_events_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    type: Mapped[str] = mapped_column(String(48), index=True)
    level: Mapped[str] = mapped_column(String(8), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SystemState(Base):
    """Singleton row (id=1)."""

    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failed_txs: Mapped[int] = mapped_column(Integer, default=0)
    last_cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reconciliation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_reconciliation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_market_data_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_universe_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    turnover_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    turnover_notional: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    bootstrapped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SimulatedBalance(Base):
    """DEMO MODE ONLY: the database-backed stand-in for a real wallet balance."""

    __tablename__ = "simulated_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True)
    quantity: Mapped[Decimal] = mapped_column(Qty, default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
