"""Strategy status rules: percentage-based, never absolute dollars."""

from __future__ import annotations

from decimal import Decimal

from zipline_engine.db.enums import StrategyStatus


def evaluate_status(
    *,
    enabled: bool,
    current_status: str,
    drawdown_pct: Decimal,
    watch_drawdown_pct: Decimal,
    disable_drawdown_pct: Decimal,
) -> tuple[StrategyStatus, str]:
    """Return (status, reason).

    * manual disable always wins
    * drawdown (time-weighted, from peak) beyond ``disable_drawdown_pct`` -> DISABLED (sticky)
    * drawdown beyond ``watch_drawdown_pct`` -> WATCH
    * otherwise ACTIVE
    """
    if not enabled:
        reason = "manually disabled" if current_status != StrategyStatus.DISABLED else "disabled"
        return StrategyStatus.DISABLED, reason
    if drawdown_pct <= -abs(disable_drawdown_pct):
        return (
            StrategyStatus.DISABLED,
            f"drawdown {drawdown_pct:.2f}% breached -{abs(disable_drawdown_pct)}%",
        )
    if drawdown_pct <= -abs(watch_drawdown_pct):
        return (
            StrategyStatus.WATCH,
            f"drawdown {drawdown_pct:.2f}% beyond -{abs(watch_drawdown_pct)}%",
        )
    return StrategyStatus.ACTIVE, "within limits"
