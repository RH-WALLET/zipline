"""Fakes for integration tests: Robinhood API, historical provider, failing adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from tests.conftest import SYMBOLS, synthetic_bars
from zipline_engine.db.enums import ExecutionMode, OrderStatus
from zipline_engine.execution.base import ExecutionAdapter, ExecutionResult, Quote, TradeRequest
from zipline_engine.marketdata.base import Bar, HistoricalMarketDataProvider
from zipline_engine.robinhood.client import RHAsset, RHDeployment, RHPrice

ADDRESSES = {s: "0x" + f"{i + 1:040x}" for i, s in enumerate(sorted(SYMBOLS))}


class FakeProvider(HistoricalMarketDataProvider):
    name = "fake"

    def __init__(self) -> None:
        self.bars = synthetic_bars()
        self.calls: list[tuple[str, date, date]] = []

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        self.calls.append((symbol, start, end))
        return [b for b in self.bars if b.symbol == symbol and start <= b.session_date <= end]


class FakeRobinhood:
    def __init__(
        self,
        symbols: list[str] | None = None,
        halted: set[str] | None = None,
        missing: set[str] | None = None,
        multipliers: dict[str, str] | None = None,
        as_of: date | None = None,
    ) -> None:
        self.symbols = sorted(symbols or SYMBOLS)
        self.halted = halted or set()
        self.missing = missing or set()
        self.multipliers = multipliers or {}
        self.bars = synthetic_bars()
        self.as_of = as_of
        self.fail = False

    def last_close(self, symbol: str) -> Decimal:
        bars = [
            b
            for b in self.bars
            if b.symbol == symbol and (self.as_of is None or b.session_date <= self.as_of)
        ]
        return bars[-1].close

    def list_assets(self) -> list[RHAsset]:
        if self.fail:
            from zipline_engine.robinhood.client import RobinhoodAPIError

            raise RobinhoodAPIError("down")
        return [
            RHAsset(
                id=f"0x{i:064x}",
                tokenSymbol=s,
                tokenName=f"{s} • Robinhood Token",
                deployments=[RHDeployment(contractAddress=ADDRESSES[s], chainId=4663)],
                currentMultiplier=Decimal(self.multipliers.get(s, "1")),
                status="ASSET_STATUS_ACTIVE",
                tradingCapabilities={
                    "market": {
                        "whole": "TRADING_STATUS_TRADABLE",
                        "fractional": "TRADING_STATUS_TRADABLE",
                    }
                },  # type: ignore[arg-type]
            )
            for i, s in enumerate(self.symbols)
            if s not in self.missing
        ]

    def get_price(self, symbol: str) -> RHPrice:
        px = self.last_close(symbol)
        return RHPrice(
            tokenSymbol=symbol,
            bid=px * Decimal("0.9995"),
            ask=px * Decimal("1.0005"),
            dailyTradingVolume=Decimal(5_000_000),
            isTradingHalt=symbol in self.halted,
            generatedAt=datetime.now(UTC),
        )

    def get_prices(self, symbols: list[str]) -> dict[str, RHPrice | Exception]:
        return {s: self.get_price(s) for s in symbols if s not in self.missing}

    def list_corporate_actions(self):  # type: ignore[no-untyped-def]
        return []


class FailingAdapter(ExecutionAdapter):
    """Pretends to be live: every execution fails (reverted). Never fills."""

    name = "failing"
    mode = ExecutionMode.LIVE

    def __init__(self, prices):  # type: ignore[no-untyped-def]
        from zipline_engine.execution.dryrun import DryRunExecutionAdapter

        self._dry = DryRunExecutionAdapter(prices)

    def quote(self, request: TradeRequest) -> Quote:
        return self._dry.quote(request)

    def execute(self, request, quote, on_submitted=None):  # type: ignore[no-untyped-def]
        return ExecutionResult(
            status=OrderStatus.FAILED,
            mode=self.mode,
            error="transaction reverted",
            tx_hash="0x" + "cd" * 32,
            block_number=1,
        )
