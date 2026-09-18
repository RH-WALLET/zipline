"""Wires services together from settings. One place decides simulated vs onchain, dry-run vs live."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.accounting.repository import BookRepository
from zipline_engine.chain.rpc import ChainClient
from zipline_engine.config import Settings
from zipline_engine.core.system import get_state
from zipline_engine.db.enums import ReconciliationStatus
from zipline_engine.db.models import Asset
from zipline_engine.events.bus import EventBus
from zipline_engine.execution.base import ExecutionAdapter
from zipline_engine.execution.dryrun import DryRunExecutionAdapter
from zipline_engine.marketdata.providers import build_provider
from zipline_engine.marketdata.service import MarketDataService
from zipline_engine.reconciliation.service import ReconciliationService
from zipline_engine.robinhood.client import RobinhoodStockTokenClient
from zipline_engine.robinhood.pricing import LivePricingService, RefPrice
from zipline_engine.robinhood.universe import UniverseService
from zipline_engine.treasury.backends import OnchainTreasury, SimulatedTreasury
from zipline_engine.treasury.funding import CapitalAllocator, FundingService
from zipline_engine.treasury.gas_oracle import GasPriceOracle
from zipline_engine.treasury.service import TreasuryService

log = logging.getLogger(__name__)


class LiveTradingBlocked(RuntimeError):
    pass


RouteProber = Callable[[str, str], tuple[bool, Decimal | None] | None]


@dataclass
class Runtime:
    settings: Settings
    session: Session
    events: EventBus
    rh_client: RobinhoodStockTokenClient
    chain: ChainClient | None
    backend: SimulatedTreasury | OnchainTreasury
    treasury: TreasuryService
    pricing: LivePricingService
    marketdata: MarketDataService
    universe: UniverseService
    repo: BookRepository
    funding: FundingService
    allocator: CapitalAllocator
    reconciler: ReconciliationService
    gas_oracle: GasPriceOracle

    @property
    def simulated(self) -> SimulatedTreasury | None:
        return self.backend if isinstance(self.backend, SimulatedTreasury) else None


def build_runtime(session: Session, settings: Settings) -> Runtime:
    events = EventBus(session)
    rh_client = RobinhoodStockTokenClient(settings.rh_stock_token_api_url)
    chain: ChainClient | None = None
    if settings.rh_rpc_url:
        chain = ChainClient(settings.rh_rpc_url, settings.chain_id)
    if settings.treasury_mode == "onchain":
        if chain is None or not settings.executor_address or not settings.cash_token_address:
            raise RuntimeError(
                "TREASURY_MODE=onchain requires RH_RPC_URL, EXECUTOR_ADDRESS and CASH_TOKEN_ADDRESS"
            )
        backend: SimulatedTreasury | OnchainTreasury = OnchainTreasury(
            chain, settings.executor_address, settings.cash_token_address, settings.chain_id
        )
    else:
        backend = SimulatedTreasury(session)
    gas_oracle = GasPriceOracle(
        settings.eth_usd_price_source, chain, settings.chainlink_eth_usd_feed
    )
    treasury = TreasuryService(session, settings, backend, gas_oracle)
    pricing = LivePricingService(session, settings, rh_client)
    marketdata = MarketDataService(
        session, build_provider(settings.history_provider, settings), settings.history_lookback_days
    )
    route_prober = _build_route_prober(settings, chain, pricing)
    universe = UniverseService(
        session, settings, rh_client, events, chain=chain, route_prober=route_prober
    )
    repo = BookRepository(session)
    funding = FundingService(session, settings, events)
    allocator = CapitalAllocator(settings)
    reconciler = ReconciliationService(session, settings, events)
    return Runtime(
        settings,
        session,
        events,
        rh_client,
        chain,
        backend,
        treasury,
        pricing,
        marketdata,
        universe,
        repo,
        funding,
        allocator,
        reconciler,
        gas_oracle,
    )


def _build_route_prober(
    settings: Settings, chain: ChainClient | None, pricing: LivePricingService
) -> RouteProber | None:
    """When 0x is configured, probe executable liquidity at universe-refresh time; otherwise None."""
    key = settings.zerox_api_key.get_secret_value()
    if not key or chain is None or not settings.cash_token_address:
        return None
    from zipline_engine.execution.zerox import ZeroXClient, ZeroXExecutionAdapter, probe_route

    client = ZeroXClient(settings.zerox_api_url, key, settings.chain_id)

    class _NoSigner:
        address = settings.executor_address or "0x" + "0" * 40

        def sign(self, tx: dict[str, Any]) -> bytes:
            raise RuntimeError("probe adapter cannot sign")

    adapter = ZeroXExecutionAdapter(
        client,
        chain,
        _NoSigner(),  # type: ignore[arg-type]
        slippage_bps=settings.max_slippage_bps,
        quote_ttl_sec=settings.quote_staleness_sec,
        min_gas_eth=settings.min_gas_eth,
        probe_impact=False,
    )
    cash_decimals = chain.erc20_decimals(settings.cash_token_address)

    def prober(symbol: str, contract: str) -> tuple[bool, Decimal | None] | None:
        asset = pricing.session.execute(
            select(Asset).where(Asset.symbol == symbol)
        ).scalar_one_or_none()
        rp = pricing.latest([asset]).get(symbol) if asset else None
        ref = rp.token_mid if rp else Decimal(0)
        return probe_route(
            adapter,
            token_address=contract,
            cash_token=settings.cash_token_address,
            cash_decimals=cash_decimals,
            probe_notional=Decimal(100),
            reference_token_price=ref,
        )

    return prober


def live_blockers(rt: Runtime) -> list[str]:
    """Everything that must be true before a single live transaction is allowed."""
    problems = rt.settings.live_trading_blockers()
    st = get_state(rt.session)
    if st.paused:
        problems.append(f"system is paused: {st.pause_reason}")
    if st.last_reconciliation_status not in (None, str(ReconciliationStatus.OK)):
        problems.append(f"last reconciliation {st.last_reconciliation_status}")
    if st.bootstrapped_at is None:
        problems.append("database not bootstrapped (run `zl bootstrap`)")
    if rt.chain is not None and not problems:
        try:
            rt.chain.verify_chain()
        except Exception as e:
            problems.append(str(e))
    return problems


def build_adapter(rt: Runtime, prices: dict[str, RefPrice]) -> ExecutionAdapter:
    """Dry-run unless LIVE_TRADING=true AND every live requirement holds. Never a silent fallback."""
    if not rt.settings.live_trading:
        return DryRunExecutionAdapter(prices)
    problems = live_blockers(rt)
    if problems:
        raise LiveTradingBlocked("; ".join(problems))
    from zipline_engine.chain.signer import LocalSigner
    from zipline_engine.execution.zerox import ZeroXClient, ZeroXExecutionAdapter

    assert rt.chain is not None
    signer = LocalSigner(rt.settings.executor_private_key.get_secret_value())
    if signer.address.lower() != rt.settings.executor_address.lower():
        raise LiveTradingBlocked("EXECUTOR_PRIVATE_KEY does not correspond to EXECUTOR_ADDRESS")
    client = ZeroXClient(
        rt.settings.zerox_api_url,
        rt.settings.zerox_api_key.get_secret_value(),
        rt.settings.chain_id,
    )
    return ZeroXExecutionAdapter(
        client,
        rt.chain,
        signer,
        slippage_bps=rt.settings.max_slippage_bps,
        quote_ttl_sec=rt.settings.quote_staleness_sec,
        min_gas_eth=rt.settings.min_gas_eth,
    )
