"""Capital allocation policies and deployable-capital math.

Only capital that exists in the treasury is ever distributed; the cash reserve is held back
at the treasury level and never enters a sleeve.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Protocol

from zipline_engine.core.money import ZERO, D, q_money


@dataclass(frozen=True)
class SleeveInfo:
    code: str
    active: bool
    configured_weight_pct: Decimal
    twr_index: Decimal = Decimal(1)
    drawdown_pct: Decimal = ZERO
    nav_volatility: Decimal | None = None


class AllocationPolicy(Protocol):
    name: str

    def target_weights(self, sleeves: list[SleeveInfo]) -> dict[str, Decimal]:
        """Fractions (sum == 1) over ACTIVE sleeves."""


def _renormalize(raw: dict[str, Decimal]) -> dict[str, Decimal]:
    positive = {k: v for k, v in raw.items() if v > 0}
    total = sum(positive.values(), ZERO)
    if total <= 0:
        return {}
    return {k: v / total for k, v in sorted(positive.items())}


class EqualWeightPolicy:
    name = "EQUAL_WEIGHT"

    def target_weights(self, sleeves: list[SleeveInfo]) -> dict[str, Decimal]:
        active = sorted(s.code for s in sleeves if s.active)
        if not active:
            return {}
        return {c: Decimal(1) / len(active) for c in active}


class ManualWeightPolicy:
    """Uses the configured weight of each active sleeve, renormalized over active sleeves."""

    name = "MANUAL"

    def target_weights(self, sleeves: list[SleeveInfo]) -> dict[str, Decimal]:
        return _renormalize({s.code: s.configured_weight_pct for s in sleeves if s.active})


class PerformanceWeightedPolicy:
    """Weights proportional to the sleeve's TWR index (floored so laggards are not starved)."""

    name = "PERFORMANCE_WEIGHTED"

    def __init__(self, floor: Decimal = Decimal("0.5")) -> None:
        self.floor = floor

    def target_weights(self, sleeves: list[SleeveInfo]) -> dict[str, Decimal]:
        return _renormalize({s.code: max(s.twr_index, self.floor) for s in sleeves if s.active})


class VolatilityAdjustedPolicy:
    """Inverse NAV-volatility weights; sleeves without a volatility estimate get the median."""

    name = "VOLATILITY_ADJUSTED"

    def target_weights(self, sleeves: list[SleeveInfo]) -> dict[str, Decimal]:
        active = [s for s in sleeves if s.active]
        vols = sorted(s.nav_volatility for s in active if s.nav_volatility and s.nav_volatility > 0)
        if not vols:
            return EqualWeightPolicy().target_weights(sleeves)
        median = vols[len(vols) // 2]
        return _renormalize({s.code: Decimal(1) / (s.nav_volatility or median) for s in active})


class DrawdownAdjustedPolicy:
    """Configured weight scaled down linearly by current drawdown (a -20% drawdown -> 80% of weight)."""

    name = "DRAWDOWN_ADJUSTED"

    def target_weights(self, sleeves: list[SleeveInfo]) -> dict[str, Decimal]:
        return _renormalize(
            {
                s.code: s.configured_weight_pct
                * max(Decimal(1) + s.drawdown_pct / 100, Decimal("0.1"))
                for s in sleeves
                if s.active
            }
        )


POLICIES: dict[str, AllocationPolicy] = {
    p.name: p  # type: ignore[misc]
    for p in (
        EqualWeightPolicy(),
        ManualWeightPolicy(),
        PerformanceWeightedPolicy(),
        VolatilityAdjustedPolicy(),
        DrawdownAdjustedPolicy(),
    )
}


def deployable_capital(nav: Decimal, cash_reserve_pct: Decimal) -> Decimal:
    """Treasury capital available to sleeves after the cash reserve."""
    if nav <= 0:
        return ZERO
    return q_money(nav * (Decimal(1) - cash_reserve_pct / 100))


def distribute(amount: Decimal, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """Split ``amount`` by ``weights`` (which need not sum to 1) so the parts sum EXACTLY to ``amount``."""
    if amount <= 0 or not weights:
        return {}
    norm = _renormalize(weights)
    parts = {
        k: (amount * w).quantize(Decimal("1e-8"), rounding=ROUND_DOWN) for k, w in norm.items()
    }
    remainder = q_money(amount) - sum(parts.values(), ZERO)
    if parts and remainder != 0:
        largest = max(parts, key=lambda k: (parts[k], k))
        parts[largest] += remainder
    return {k: v for k, v in parts.items() if v != 0}


def check_max_strategy_allocation(
    weights: dict[str, Decimal], max_pct: Decimal, cash_reserve_pct: Decimal
) -> list[str]:
    """Sleeve share of TREASURY NAV = weight × (1 − reserve). Returns violations (empty == OK)."""
    deploy_frac = Decimal(1) - cash_reserve_pct / 100
    out = []
    for code, w in weights.items():
        share = w * deploy_frac * 100
        if share > max_pct + Decimal("1e-9"):
            out.append(f"{code}: {share:.2f}% of NAV exceeds MAX_STRATEGY_ALLOCATION_PCT={max_pct}")
    return out


def to_pct(fraction: Decimal) -> Decimal:
    return D(fraction) * 100
