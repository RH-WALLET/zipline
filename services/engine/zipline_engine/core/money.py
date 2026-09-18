"""Decimal helpers. All accounting is done in ``Decimal``; floats never touch balances."""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, getcontext
from typing import Any

getcontext().prec = 50

ZERO = Decimal(0)
ONE = Decimal(1)
BPS = Decimal(10_000)
QTY_PLACES = Decimal("1e-18")
MONEY_PLACES = Decimal("1e-8")
WEI = Decimal(10) ** 18


def D(value: Any) -> Decimal:
    """Lossless conversion to Decimal (floats go through ``repr`` to avoid binary noise)."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    if hasattr(value, "item") and not isinstance(
        value, str | bytes
    ):  # numpy scalar -> python scalar
        value = value.item()
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def q_qty(value: Decimal) -> Decimal:
    return value.quantize(QTY_PLACES, rounding=ROUND_DOWN)


def q_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_PLACES, rounding=ROUND_HALF_EVEN)


def pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole == 0:
        return ZERO
    return part / whole * Decimal(100)


def bps_diff(actual: Decimal, reference: Decimal) -> Decimal:
    """(actual - reference) / reference in basis points. Positive = actual above reference."""
    if reference == 0:
        return ZERO
    return (actual - reference) / reference * BPS


def to_wei(amount: Decimal, decimals: int = 18) -> int:
    return int((amount * (Decimal(10) ** decimals)).to_integral_value(rounding=ROUND_DOWN))


def from_wei(amount: int | str, decimals: int = 18) -> Decimal:
    return Decimal(int(amount)) / (Decimal(10) ** decimals)


def safe_div(a: Decimal, b: Decimal) -> Decimal:
    return ZERO if b == 0 else a / b
