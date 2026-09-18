"""Pre-trade validation. Every function raises ``TradeRejected`` with a stable reason code."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from zipline_engine.core.money import ZERO
from zipline_engine.db.enums import Side
from zipline_engine.execution.base import Quote, TradeRejected, TradeRequest
from zipline_engine.robinhood.pricing import RefPrice


def _is_hex_address(value: str | None) -> bool:
    if not value or not value.startswith("0x") or len(value) != 42:
        return False
    try:
        int(value[2:], 16)
    except ValueError:
        return False
    return True


def validate_token_addresses(
    request: TradeRequest, expected_token: str, expected_cash: str
) -> None:
    if not _is_hex_address(request.token_address):
        raise TradeRejected("UNKNOWN_TOKEN", f"{request.symbol} has no valid contract address")
    if request.token_address.lower() != expected_token.lower():
        raise TradeRejected(
            "UNKNOWN_TOKEN", f"{request.symbol} address mismatch with registered deployment"
        )
    if (
        not _is_hex_address(request.cash_token_address)
        or request.cash_token_address.lower() != expected_cash.lower()
    ):
        raise TradeRejected(
            "UNSUPPORTED_TOKEN", "cash token address is not the configured CASH_TOKEN_ADDRESS"
        )
    if request.token_address.lower() == request.cash_token_address.lower():
        raise TradeRejected("UNSUPPORTED_TOKEN", "token and cash token are identical")


def validate_asset_status(
    *,
    symbol: str,
    eligible: bool,
    hold_only: bool,
    halted: bool,
    side: Side,
    verified_onchain: bool | None,
    require_verified: bool,
) -> None:
    if halted:
        raise TradeRejected("HALTED", f"{symbol} trading is halted")
    if not eligible and not (hold_only and side == Side.SELL):
        raise TradeRejected("UNSUPPORTED_TOKEN", f"{symbol} is not in the eligible universe")
    if require_verified and verified_onchain is not True:
        raise TradeRejected(
            "NON_STOCK_TOKEN", f"{symbol} deployment not verified as a Stock Token contract onchain"
        )


def validate_reference_price(
    rp: RefPrice | None, symbol: str, staleness_sec: int, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    if rp is None:
        raise TradeRejected("NO_PRICE", f"no reference price for {symbol}")
    if rp.source != "robinhood_api":
        raise TradeRejected("STALE_PRICE", f"{symbol} reference price is {rp.source}, not live")
    if rp.generated_at is not None:
        age = (now - rp.generated_at.astimezone(UTC)).total_seconds()
        if age > staleness_sec:
            raise TradeRejected(
                "STALE_PRICE", f"{symbol} price is {age:.0f}s old (limit {staleness_sec}s)"
            )
    if rp.underlying_mid <= 0:
        raise TradeRejected("NO_PRICE", f"{symbol} has a non-positive price")


def validate_balance(
    request: TradeRequest, *, treasury_cash: Decimal, treasury_position: Decimal
) -> None:
    if request.side == Side.BUY and request.notional > treasury_cash:
        raise TradeRejected(
            "INSUFFICIENT_BALANCE",
            f"buy {request.notional:.4f} exceeds treasury cash {treasury_cash:.4f}",
        )
    if request.side == Side.SELL and request.quantity > treasury_position + Decimal("1e-12"):
        raise TradeRejected(
            "INSUFFICIENT_BALANCE",
            f"sell {request.quantity} exceeds treasury position {treasury_position}",
        )


def validate_gas(gas_eth: Decimal, min_gas_eth: Decimal, live: bool) -> None:
    if live and gas_eth < min_gas_eth:
        raise TradeRejected(
            "INSUFFICIENT_GAS", f"ETH balance {gas_eth:.6f} below MIN_GAS_ETH {min_gas_eth}"
        )


def validate_order_size(
    request: TradeRequest,
    *,
    treasury_nav: Decimal,
    max_order_pct: Decimal,
    turnover_today: Decimal,
    max_turnover_pct: Decimal,
) -> None:
    notional = (
        request.notional if request.side == Side.BUY else request.quantity * request.reference_price
    )
    if treasury_nav <= 0:
        raise TradeRejected("OVERSIZED_ORDER", "treasury NAV is zero")
    if notional > treasury_nav * max_order_pct / 100 * Decimal("1.0001"):
        raise TradeRejected(
            "OVERSIZED_ORDER",
            f"{notional:.4f} exceeds MAX_ORDER_PCT_OF_TREASURY {max_order_pct}% of {treasury_nav:.4f}",
        )
    if turnover_today + notional > treasury_nav * max_turnover_pct / 100 * Decimal("1.0001"):
        raise TradeRejected(
            "DAILY_TURNOVER",
            f"turnover {turnover_today + notional:.4f} would exceed MAX_DAILY_TURNOVER_PCT {max_turnover_pct}%",
        )


def validate_quote(
    quote: Quote,
    request: TradeRequest,
    *,
    max_slippage_bps: int,
    max_price_impact_bps: int,
    quote_staleness_sec: int,
    now: datetime | None = None,
) -> Decimal:
    """Returns the quote's deviation from the reference (bps, adverse positive)."""
    now = now or datetime.now(UTC)
    if not quote.liquidity_available:
        raise TradeRejected("NO_LIQUIDITY", f"no executable liquidity for {request.symbol}")
    if (
        quote.sell_token.lower() != request.sell_token.lower()
        or quote.buy_token.lower() != request.buy_token.lower()
    ):
        raise TradeRejected("UNKNOWN_TOKEN", "quote tokens do not match the request")
    if quote.sell_amount_raw <= 0 or quote.buy_amount_raw <= 0 or quote.price <= 0:
        raise TradeRejected("NO_LIQUIDITY", "quote has zero amounts")
    age = (now - quote.quoted_at).total_seconds()
    if age > quote_staleness_sec:
        raise TradeRejected(
            "STALE_QUOTE", f"quote is {age:.0f}s old (limit {quote_staleness_sec}s)"
        )
    ref = request.reference_price
    if ref <= 0:
        raise TradeRejected("NO_PRICE", "reference price missing")
    adverse = (quote.price / ref - 1) if request.side == Side.BUY else (ref / quote.price - 1)
    deviation_bps = max(adverse, ZERO) * Decimal(10_000)
    if deviation_bps > max_slippage_bps:
        raise TradeRejected(
            "EXCESSIVE_SLIPPAGE",
            f"quote {deviation_bps:.1f} bps worse than reference (limit {max_slippage_bps})",
        )
    impact = quote.price_impact_bps if quote.price_impact_bps is not None else deviation_bps
    if impact > max_price_impact_bps:
        raise TradeRejected(
            "EXCESSIVE_PRICE_IMPACT",
            f"price impact {impact:.1f} bps exceeds limit {max_price_impact_bps}",
        )
    if quote.issues.get("balance"):
        raise TradeRejected(
            "INSUFFICIENT_BALANCE",
            f"quote provider reports insufficient balance: {quote.issues['balance']}",
        )
    return deviation_bps
