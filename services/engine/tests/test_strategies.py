"""Strategy determinism, long-only/no-leverage invariants, ZEROIQ reproducibility."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from tests.conftest import SYMBOLS
from zipline_engine.strategies.base import StrategyContext, normalize_weights
from zipline_engine.strategies.registry import STRATEGY_CLASSES, all_strategies, build_strategy
from zipline_engine.strategies.zeroiq import derive_stream_seed


def ctx(panel, state=None, universe=None, ordinal=100):  # type: ignore[no-untyped-def]
    return StrategyContext(
        session_date=date(2026, 9, 17),
        universe=sorted(universe or SYMBOLS),
        panel=panel,
        current_weights={},
        state=dict(state or {}),
        params={},
        benchmark="SPY",
        session_ordinal=ordinal,
    )


@pytest.mark.parametrize("cls", STRATEGY_CLASSES)
def test_same_inputs_same_outputs(cls, panel):  # type: ignore[no-untyped-def]
    strat = cls()
    state = {"seed": 12345} if cls.code == "ZEROIQ" else {}
    a = strat.run(ctx(panel, state))
    b = strat.run(ctx(panel, state))
    assert a.target_weights == b.target_weights
    assert [(s.kind, s.symbol, s.value) for s in a.signals] == [
        (s.kind, s.symbol, s.value) for s in b.signals
    ]
    assert a.new_state == b.new_state


@pytest.mark.parametrize("cls", STRATEGY_CLASSES)
def test_long_only_and_no_leverage(cls, panel):  # type: ignore[no-untyped-def]
    out = cls().run(ctx(panel, {"seed": 1}))
    total = sum(out.target_weights.values(), Decimal(0))
    assert total <= Decimal("1.00000001")
    assert all(w >= 0 for w in out.target_weights.values())
    assert set(out.target_weights) <= set(SYMBOLS)


def test_version_hash_changes_with_params() -> None:
    a, b = build_strategy("TREND"), build_strategy("TREND", {"fast": 40})
    assert a.get_version_hash() != b.get_version_hash()
    assert a.source_hash() == b.source_hash()
    assert len(a.get_version_hash()) == 16


def test_all_ten_registered() -> None:
    codes = [s.code for s in all_strategies()]
    assert codes == [
        "TREND",
        "MOMENTUM",
        "MEANREV",
        "BREAKOUT",
        "LOWVOL",
        "REVERSAL",
        "DUALMA",
        "RISKON",
        "PAIRS",
        "ZEROIQ",
    ]
    for s in all_strategies():
        rules = s.describe_rules()
        assert "parameters" in rules and rules  # every strategy documents itself


def test_insufficient_history_goes_to_cash(panel):  # type: ignore[no-untyped-def]
    short = panel.__class__(
        panel.close.tail(30),
        panel.high.tail(30),
        panel.low.tail(30),
        panel.open.tail(30),
        panel.volume.tail(30),
        "test",
    )
    out = build_strategy("MOMENTUM").run(ctx(short))
    assert out.target_weights == {}
    assert out.signals[0].kind == "INSUFFICIENT_HISTORY"


def test_weights_never_outside_universe(panel):  # type: ignore[no-untyped-def]
    universe = ["AAPL", "MSFT"]  # NVDA etc. removed from eligibility
    for cls in STRATEGY_CLASSES:
        out = cls().run(ctx(panel, {"seed": 3, "held": ["NVDA", "AAPL"]}, universe))
        assert set(out.target_weights) <= set(universe), cls.code


def test_zeroiq_reproducible_and_seed_sensitive(panel):  # type: ignore[no-untyped-def]
    z = build_strategy("ZEROIQ")
    a = z.run(ctx(panel, {"seed": 42}, ordinal=500))
    b = z.run(ctx(panel, {"seed": 42}, ordinal=500))
    c = z.run(ctx(panel, {"seed": 43}, ordinal=500))
    assert a.target_weights == b.target_weights and a.target_weights
    assert a.target_weights != c.target_weights
    assert a.new_state["last_stream_seed"] == str(derive_stream_seed(42, 500, sorted(SYMBOLS)))
    # holds between draws, redraws after hold_sessions
    held = z.run(ctx(panel, a.new_state, ordinal=502))
    assert held.target_weights == a.target_weights
    redraw = z.run(ctx(panel, a.new_state, ordinal=505))
    assert redraw.new_state["last_rebalance_ordinal"] == 505


def test_zeroiq_without_seed_is_cash(panel):  # type: ignore[no-untyped-def]
    out = build_strategy("ZEROIQ").run(ctx(panel, {}))
    assert out.target_weights == {}


def test_normalize_weights_caps_and_sums() -> None:
    w = normalize_weights({"A": 10.0, "B": 1.0, "C": 1.0}, gross=1.0, cap=0.5)
    assert sum(w.values()) <= Decimal("1.00000001")
    assert w["A"] <= Decimal("0.50000001")
    assert w["B"] == w["C"]


def test_riskon_regime_off_is_cash(panel):  # type: ignore[no-untyped-def]
    strat = build_strategy("RISKON", {"max_regime_vol": 0.0})  # impossible threshold -> regime off
    out = strat.run(ctx(panel))
    assert out.target_weights == {}
    assert any(s.kind == "REGIME_OFF" for s in out.signals)
