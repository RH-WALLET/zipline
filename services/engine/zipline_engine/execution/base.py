"""Execution adapter interface. The quantitative engine never signs; adapters do."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from zipline_engine.db.enums import ExecutionMode, OrderStatus, Side, TxKind, TxStatus


@dataclass(frozen=True)
class TradeRequest:
    symbol: str
    asset_id: int
    side: Side
    quantity: Decimal  # raw tokens to sell (SELL) or expected to receive (BUY, informational)
    notional: Decimal  # cash to spend (BUY) or expected proceeds (SELL, informational)
    reference_price: Decimal  # USD per raw token (Robinhood mid × multiplier)
    token_address: str
    token_decimals: int
    cash_token_address: str
    cash_decimals: int
    taker: str | None

    @property
    def sell_token(self) -> str:
        return self.cash_token_address if self.side == Side.BUY else self.token_address

    @property
    def buy_token(self) -> str:
        return self.token_address if self.side == Side.BUY else self.cash_token_address


@dataclass
class Quote:
    provider: str
    sell_token: str
    buy_token: str
    sell_amount_raw: int
    buy_amount_raw: int
    min_buy_amount_raw: int | None
    price: Decimal  # USD per raw token implied by the quote
    quoted_at: datetime
    expires_at: datetime | None = None
    price_impact_bps: Decimal | None = None
    gas_estimate: int | None = None
    gas_price_wei: int | None = None
    allowance_spender: str | None = None
    allowance_required: bool = False
    liquidity_available: bool = True
    route: dict[str, Any] = field(default_factory=dict)
    transaction: dict[str, Any] | None = None
    issues: dict[str, Any] = field(default_factory=dict)

    def quantity(self, side: Side, token_decimals: int, cash_decimals: int) -> Decimal:
        """Raw-token quantity the quote would trade."""
        raw = self.buy_amount_raw if side == Side.BUY else self.sell_amount_raw
        return Decimal(raw) / (Decimal(10) ** token_decimals)

    def notional(self, side: Side, token_decimals: int, cash_decimals: int) -> Decimal:
        raw = self.sell_amount_raw if side == Side.BUY else self.buy_amount_raw
        return Decimal(raw) / (Decimal(10) ** cash_decimals)


@dataclass
class TxRecord:
    kind: TxKind
    tx_hash: str
    from_address: str
    to_address: str
    status: TxStatus
    nonce: int | None = None
    gas_limit: int | None = None
    gas_used: int | None = None
    effective_gas_price_wei: int | None = None
    block_number: int | None = None
    error: str | None = None

    @property
    def gas_cost_eth(self) -> Decimal | None:
        if self.gas_used is None or self.effective_gas_price_wei is None:
            return None
        return Decimal(self.gas_used * self.effective_gas_price_wei) / Decimal(10) ** 18


@dataclass
class ExecutionResult:
    status: OrderStatus
    mode: ExecutionMode
    executed_quantity: Decimal | None = None
    executed_notional: Decimal | None = None
    effective_price: Decimal | None = None
    slippage_bps: Decimal | None = None
    price_impact_bps: Decimal | None = None
    gas_used: int | None = None
    gas_cost_eth: Decimal | None = None
    tx_hash: str | None = None
    block_number: int | None = None
    error: str | None = None
    transactions: list[TxRecord] = field(default_factory=list)

    @property
    def filled(self) -> bool:
        return self.status in (OrderStatus.CONFIRMED, OrderStatus.DRY_RUN_FILLED) and bool(
            self.executed_quantity
        )


class TradeRejected(Exception):
    """Pre-trade validation failure. Nothing was broadcast."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ExecutionAdapter(ABC):
    name: str = "abstract"
    mode: ExecutionMode = ExecutionMode.DRY_RUN

    @abstractmethod
    def quote(self, request: TradeRequest) -> Quote: ...

    @abstractmethod
    def execute(
        self,
        request: TradeRequest,
        quote: Quote,
        on_submitted: Callable[[TxRecord], None] | None = None,
    ) -> ExecutionResult: ...
