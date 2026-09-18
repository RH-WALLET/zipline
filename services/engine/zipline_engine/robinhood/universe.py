"""Asset universe: live Robinhood Stock Token list ∩ configured allowlist, gated by eligibility.

An asset may trade only when ALL of these hold:
  1. it exists in the Stock Token API
  2. it has a deployment on the configured chain (and, when an RPC is available, the
     contract has code, 18 decimals and a readable ERC-8056 multiplier)
  3. status == ASSET_STATUS_ACTIVE
  4. it is currently tradable (priced, ask >= bid > 0)
  5. it is not halted
  6. current underlying pricing is present
  7. executable liquidity exists (daily volume > 0; and a live route probe when 0x is configured)
  8. probe price impact within MAX_PRICE_IMPACT_BPS (when probed)

Assets that fail because they are temporarily unavailable (halted, unpriced, missing from a
response) are HOLD-ONLY: existing positions are carried, nothing new is opened. Assets that
are inactive or dropped from the allowlist are liquidated when a route exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.config import Settings
from zipline_engine.core.money import D
from zipline_engine.db.enums import AssetStatus, EventLevel, EventType
from zipline_engine.db.models import Asset, AssetDeployment
from zipline_engine.events.bus import EventBus
from zipline_engine.robinhood.client import (
    RHPrice,
    RobinhoodAPIError,
    RobinhoodStockTokenClient,
)

log = logging.getLogger(__name__)

HOLD_ONLY_REASONS = {
    "halted",
    "no_price",
    "invalid_price",
    "not_in_api_response",
    "api_unavailable",
}


@dataclass
class EligibilityInput:
    symbol: str
    in_allowlist: bool
    seen_in_api: bool
    status: str
    tradable: bool
    has_deployment: bool
    contract_verified: bool | None  # None == not checked (no RPC)
    decimals_ok: bool | None
    price: RHPrice | None
    daily_volume: Decimal | None
    route_ok: bool | None = None  # None == not probed
    probe_impact_bps: Decimal | None = None
    max_impact_bps: int = 150


@dataclass
class Eligibility:
    eligible: bool
    hold_only: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_eligibility(i: EligibilityInput) -> Eligibility:
    reasons: list[str] = []
    if not i.in_allowlist:
        reasons.append("not_in_allowlist")
    if not i.seen_in_api:
        reasons.append("not_in_api_response")
    if i.status != AssetStatus.ACTIVE:
        reasons.append(f"status:{i.status}")
    if not i.tradable:
        reasons.append("not_tradable")
    if not i.has_deployment:
        reasons.append("no_deployment_on_chain")
    if i.contract_verified is False:
        reasons.append("contract_not_found_onchain")
    if i.decimals_ok is False:
        reasons.append("unexpected_decimals")
    if i.price is None:
        reasons.append("no_price")
    else:
        if i.price.isTradingHalt:
            reasons.append("halted")
        if not i.price.valid:
            reasons.append("invalid_price")
    if i.daily_volume is not None and i.daily_volume <= 0:
        reasons.append("no_reported_volume")
    if i.route_ok is False:
        reasons.append("no_execution_route")
    if i.probe_impact_bps is not None and i.probe_impact_bps > i.max_impact_bps:
        reasons.append(f"price_impact_{i.probe_impact_bps:.0f}bps>{i.max_impact_bps}")
    eligible = not reasons
    hold_only = (not eligible) and all(r in HOLD_ONLY_REASONS for r in reasons)
    return Eligibility(eligible=eligible, hold_only=hold_only, reasons=reasons)


@dataclass
class UniverseReport:
    source: str
    eligible: list[str] = field(default_factory=list)
    hold_only: list[str] = field(default_factory=list)
    ineligible: dict[str, list[str]] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    error: str | None = None


class UniverseService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        rh_client: RobinhoodStockTokenClient,
        events: EventBus,
        chain: object | None = None,
        route_prober: object | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.rh = rh_client
        self.events = events
        self.chain = chain  # ChainClient or None
        self.route_prober = route_prober  # callable(symbol, contract) -> (ok, impact_bps) or None

    # ------------------------------------------------------------------ queries
    def all_assets(self) -> list[Asset]:
        return list(self.session.execute(select(Asset).order_by(Asset.symbol)).scalars().all())

    def eligible_assets(self) -> list[Asset]:
        return [a for a in self.all_assets() if a.eligible]

    def asset_by_symbol(self, symbol: str) -> Asset | None:
        return self.session.execute(
            select(Asset).where(Asset.symbol == symbol.upper())
        ).scalar_one_or_none()

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> UniverseReport:
        allow = self.settings.allowlist
        chain_id = self.settings.chain_id
        previously_eligible = {a.symbol for a in self.eligible_assets()}
        try:
            api_assets = {a.symbol: a for a in self.rh.list_assets()}
        except RobinhoodAPIError as e:
            msg = f"Stock Token API unavailable: {e}"
            self.events.emit(EventType.CONFIG_WARNING, msg, level=EventLevel.WARN)
            return self._degraded_report(previously_eligible, msg)

        wanted = [s for s in allow if s in api_assets]
        prices = self.rh.get_prices(wanted)
        report = UniverseReport(source="robinhood_api")
        now = datetime.now(UTC)

        for symbol in allow:
            rh_asset = api_assets.get(symbol)
            asset = self.asset_by_symbol(symbol) or Asset(symbol=symbol)
            asset.in_allowlist = True
            deployment = rh_asset.deployment_on(chain_id) if rh_asset else None
            price_obj = prices.get(symbol)
            price = price_obj if isinstance(price_obj, RHPrice) else None

            if rh_asset:
                asset.name = rh_asset.tokenName or asset.name
                asset.rh_asset_id = rh_asset.id or asset.rh_asset_id
                asset.status = rh_asset.status
                asset.current_multiplier = rh_asset.currentMultiplier
                asset.pending_multiplier = rh_asset.pendingMultiplier
                asset.pending_multiplier_effective_at = rh_asset.pendingMultiplierEffectiveTime
                asset.fractional_tradability = rh_asset.tradingCapabilities.fractional_tradable
                asset.all_day_tradability = rh_asset.tradingCapabilities.all_day_tradable
                asset.extended_hours_fractional_tradability = (
                    rh_asset.tradingCapabilities.extended_fractional_tradable
                )
                asset.isin = rh_asset.isin or asset.isin
                asset.logo_url = rh_asset.logoUrl
                asset.last_seen_at = now
            asset.is_halted = bool(price.isTradingHalt) if price else asset.is_halted

            contract_verified: bool | None = None
            decimals_ok: bool | None = None
            if deployment:
                dep = self._upsert_deployment(asset, deployment.contractAddress, chain_id)
                if rh_asset is not None:
                    dep.decimals = int(rh_asset.tokenDecimals or 18)
                if self.chain is not None:
                    contract_verified, decimals_ok = self._verify_onchain(dep)
            route_ok, impact = None, None
            if deployment and self.route_prober is not None and price and price.valid:
                try:
                    probe = self.route_prober(symbol, deployment.contractAddress)  # type: ignore[operator]
                    if probe is not None:
                        route_ok, impact = probe
                except Exception as e:  # probe failure == unknown, not ineligible
                    log.warning("route probe failed for %s: %s", symbol, e)

            # an asset missing from one response keeps its persisted deployment and flags:
            # it becomes HOLD-ONLY (carried, not traded) instead of being force-liquidated
            known_deployment = deployment is not None or any(
                d.chain_id == chain_id for d in asset.deployments
            )
            elig = evaluate_eligibility(
                EligibilityInput(
                    symbol=symbol,
                    in_allowlist=True,
                    seen_in_api=rh_asset is not None,
                    status=asset.status,
                    tradable=rh_asset.tradingCapabilities.any_tradable if rh_asset else True,
                    has_deployment=known_deployment,
                    contract_verified=contract_verified,
                    decimals_ok=decimals_ok,
                    price=price,
                    daily_volume=price.dailyTradingVolume if price else None,
                    route_ok=route_ok,
                    probe_impact_bps=impact,
                    max_impact_bps=self.settings.max_price_impact_bps,
                )
            )
            asset.eligible = elig.eligible
            asset.eligibility_reasons = [*elig.reasons, *(["hold_only"] if elig.hold_only else [])]
            self.session.add(asset)
            if elig.eligible:
                report.eligible.append(symbol)
            elif elig.hold_only:
                report.hold_only.append(symbol)
                report.ineligible[symbol] = elig.reasons
            else:
                report.ineligible[symbol] = elig.reasons

        # assets that fell out of the allowlist entirely
        for asset in self.all_assets():
            if asset.symbol not in allow and (asset.in_allowlist or asset.eligible):
                asset.in_allowlist = False
                asset.eligible = False
                asset.eligibility_reasons = ["not_in_allowlist"]
                self.session.add(asset)

        self.session.flush()
        now_eligible = set(report.eligible)
        report.removed = sorted(previously_eligible - now_eligible)
        report.added = sorted(now_eligible - previously_eligible)
        for s in report.removed:
            self.events.emit(
                EventType.ASSET_REMOVED,
                f"{s} left the eligible universe: {', '.join(report.ineligible.get(s, ['unknown']))}",
                level=EventLevel.WARN,
                payload={"symbol": s, "reasons": report.ineligible.get(s, [])},
            )
        self.events.emit(
            EventType.UNIVERSE_UPDATED,
            f"universe refreshed: {len(report.eligible)} eligible, {len(report.hold_only)} hold-only, "
            f"{len(report.ineligible) - len(report.hold_only)} ineligible",
            payload={
                "eligible": report.eligible,
                "hold_only": report.hold_only,
                "ineligible": report.ineligible,
                "added": report.added,
                "removed": report.removed,
            },
        )
        return report

    def _degraded_report(self, previously_eligible: set[str], error: str) -> UniverseReport:
        report = UniverseReport(source="cache", error=error)
        report.eligible = sorted(previously_eligible)
        return report

    def _upsert_deployment(self, asset: Asset, contract: str, chain_id: int) -> AssetDeployment:
        from zipline_engine.chain.rpc import checksum

        addr = checksum(contract)
        for d in asset.deployments:
            if d.chain_id == chain_id:
                d.contract_address = addr
                return d
        dep = AssetDeployment(chain_id=chain_id, contract_address=addr, decimals=18)
        asset.deployments.append(dep)
        return dep

    def _verify_onchain(self, dep: AssetDeployment) -> tuple[bool | None, bool | None]:
        try:
            has_code = bool(self.chain.has_code(dep.contract_address))  # type: ignore[union-attr]
            if not has_code:
                dep.verified_onchain = False
                return False, None
            decimals = int(self.chain.erc20_decimals(dep.contract_address))  # type: ignore[union-attr]
            dep.decimals = decimals
            mult = self.chain.ui_multiplier(dep.contract_address)  # type: ignore[union-attr]
            dep.onchain_multiplier = D(mult) if mult is not None else None
            dep.verified_onchain = True
            dep.last_verified_at = datetime.now(UTC)
            return True, decimals == 18
        except Exception as e:
            log.warning("onchain verification failed for %s: %s", dep.contract_address, e)
            return None, None
