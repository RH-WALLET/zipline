"""Robinhood Stock Token multiplier semantics (ERC-8056 scaled UI amount).

* ``balanceOf`` returns a RAW token amount (18 decimals) that never rebases.
* ``uiMultiplier()`` is scaled by 1e18. At launch it is exactly 1e18 (one token == one share).
* Corporate actions (splits, dividends) change the multiplier, not the raw balance:

      underlying_shares = raw_tokens * multiplier

  where ``multiplier = uiMultiplier / 1e18``.
* Robinhood's ``/prices`` endpoint quotes the UNDERLYING per-share bid/ask and is NOT
  multiplier-adjusted. Therefore the USD value of a raw token is::

      token_price = underlying_price * multiplier

* Chainlink Stock Token feeds are already multiplier-adjusted; never apply it twice.

Everything downstream (books, netting, orders) works in raw token units so that a 2:1
split doubles ``multiplier``, halves ``underlying_price`` and leaves value and PnL intact.
"""

from __future__ import annotations

from decimal import Decimal

from zipline_engine.core.money import WEI, D, q_qty

UI_MULTIPLIER_SCALE = WEI


def multiplier_from_ui(ui_multiplier: int | str | Decimal) -> Decimal:
    """Convert the on-chain ``uiMultiplier()`` integer (1e18-scaled) to a plain ratio."""
    return D(ui_multiplier) / UI_MULTIPLIER_SCALE


def parse_api_multiplier(value: str | float | int | Decimal | None) -> Decimal:
    """``currentMultiplier`` from the REST API is a plain ratio string such as ``"1"`` or ``"2.5"``."""
    if value is None:
        return Decimal(1)
    m = D(value)
    if m <= 0:
        raise ValueError(f"invalid multiplier {value!r}")
    return m


def token_price(underlying_price: Decimal, multiplier: Decimal) -> Decimal:
    """USD value of ONE raw token given the underlying per-share price."""
    return underlying_price * multiplier


def shares_from_tokens(raw_tokens: Decimal, multiplier: Decimal) -> Decimal:
    return raw_tokens * multiplier


def tokens_for_notional(
    notional_usd: Decimal, underlying_price: Decimal, multiplier: Decimal
) -> Decimal:
    """Raw tokens purchasable with ``notional_usd`` at the given underlying price."""
    px = token_price(underlying_price, multiplier)
    if px <= 0:
        raise ValueError("price must be positive")
    return q_qty(notional_usd / px)


def position_value(raw_tokens: Decimal, underlying_price: Decimal, multiplier: Decimal) -> Decimal:
    return raw_tokens * token_price(underlying_price, multiplier)
