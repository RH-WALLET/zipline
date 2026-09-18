"""DryRunExecutionAdapter: DEMO MODE fills. Nothing touches the network.

Fills are simulated at Robinhood's underlying ask (buys) / bid (sells) × multiplier — i.e. the
treasury pays the quoted spread but no onchain liquidity is consumed, no gas is spent and no
transaction exists. Identifiers are obviously local (``dry-000042``); there is never a hash.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from zipline_engine.core.money import q_qty, to_wei
from zipline_engine.db.enums import ExecutionMode, OrderStatus, Side
from zipline_engine.execution.base import (
    ExecutionAdapter,
    ExecutionResult,
    Quote,
    TradeRequest,
    TxRecord,
)
from zipline_engine.robinhood.pricing import RefPrice


class DryRunExecutionAdapter(ExecutionAdapter):
    name = "dryrun"
    mode = ExecutionMode.DRY_RUN

    def __init__(self, prices: dict[str, RefPrice]) -> None:
        self.prices = prices

    def _fill_price(self, request: TradeRequest) -> Decimal:
        rp = self.prices.get(request.symbol)
        if rp is None:
            raise LookupError(f"no reference price for {request.symbol}")
        return rp.token_ask if request.side == Side.BUY else rp.token_bid

    def quote(self, request: TradeRequest) -> Quote:
        px = self._fill_price(request)
        if request.side == Side.BUY:
            qty = q_qty(request.notional / px)
            sell_raw, buy_raw = (
                to_wei(request.notional, request.cash_decimals),
                to_wei(qty, request.token_decimals),
            )
        else:
            qty = request.quantity
            sell_raw, buy_raw = (
                to_wei(qty, request.token_decimals),
                to_wei(qty * px, request.cash_decimals),
            )
        return Quote(
            provider=self.name,
            sell_token=request.sell_token,
            buy_token=request.buy_token,
            sell_amount_raw=sell_raw,
            buy_amount_raw=buy_raw,
            min_buy_amount_raw=buy_raw,
            price=px,
            quoted_at=datetime.now(UTC),
            price_impact_bps=None,  # unknown: no onchain liquidity was consulted
            liquidity_available=True,
            route={
                "note": "DRY RUN — simulated at Robinhood underlying bid/ask × multiplier; no route"
            },
        )

    def execute(
        self,
        request: TradeRequest,
        quote: Quote,
        on_submitted: Callable[[TxRecord], None] | None = None,
    ) -> ExecutionResult:
        qty = quote.quantity(request.side, request.token_decimals, request.cash_decimals)
        notional = quote.notional(request.side, request.token_decimals, request.cash_decimals)
        eff = notional / qty if qty > 0 else quote.price
        slippage = (
            (eff / request.reference_price - 1) * Decimal(10_000)
            if request.reference_price
            else Decimal(0)
        )
        if request.side == Side.SELL:
            slippage = -slippage
        return ExecutionResult(
            status=OrderStatus.DRY_RUN_FILLED,
            mode=self.mode,
            executed_quantity=qty,
            executed_notional=notional,
            effective_price=eff,
            slippage_bps=slippage,
            price_impact_bps=None,
            gas_used=None,
            gas_cost_eth=None,
            tx_hash=None,
            block_number=None,
            transactions=[],
        )
