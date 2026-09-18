"""TreasuryService: the one real pool of capital, valued and snapshotted."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zipline_engine.accounting.allocation import deployable_capital
from zipline_engine.accounting.books import Book
from zipline_engine.config import Settings
from zipline_engine.core.money import ZERO, D, q_money
from zipline_engine.db.models import (
    Asset,
    BlockchainTransaction,
    FundingEvent,
    TreasurySnapshot,
    WithdrawalEvent,
)
from zipline_engine.robinhood.pricing import RefPrice
from zipline_engine.treasury.backends import OnchainTreasury, SimulatedTreasury, TreasuryBalances
from zipline_engine.treasury.gas_oracle import GasPriceOracle


@dataclass
class FundingTotals:
    base_capital: Decimal = ZERO
    contributions: Decimal = ZERO
    withdrawals: Decimal = ZERO
    cumulative_gas_eth: Decimal = ZERO
    cumulative_gas_usd: Decimal = ZERO

    @property
    def net_external(self) -> Decimal:
        return self.base_capital + self.contributions - self.withdrawals


@dataclass
class TreasuryValuation:
    balances: TreasuryBalances
    nav: Decimal
    cash: Decimal
    positions_value: Decimal
    deployable_capital: Decimal
    reserve_target: Decimal
    gas_eth: Decimal
    gas_usd: Decimal | None
    eth_usd: Decimal | None
    positions: dict[str, dict[str, str]] = field(default_factory=dict)
    missing_prices: list[str] = field(default_factory=list)


class TreasuryService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        backend: SimulatedTreasury | OnchainTreasury,
        gas_oracle: GasPriceOracle | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.backend = backend
        self.gas_oracle = gas_oracle

    @property
    def mode(self) -> str:
        return self.backend.mode

    def read_balances(self, assets: list[Asset]) -> TreasuryBalances:
        return self.backend.read_balances(assets)

    def value(self, balances: TreasuryBalances, prices: dict[str, RefPrice]) -> TreasuryValuation:
        pv = ZERO
        detail: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        for sym, qty in balances.positions.items():
            rp = prices.get(sym)
            if rp is None:
                missing.append(sym)
                continue
            value = qty * rp.token_mid
            pv += value
            detail[sym] = {
                "quantity": str(qty),
                "underlying_mid": str(q_money(rp.underlying_mid)),
                "multiplier": str(rp.multiplier),
                "token_price": str(q_money(rp.token_mid)),
                "value": str(q_money(value)),
                "price_source": rp.source,
                "stale": str(rp.stale).lower(),
            }
        nav = balances.cash + pv
        eth_usd = self.gas_oracle.eth_usd() if self.gas_oracle else None
        return TreasuryValuation(
            balances=balances,
            nav=q_money(nav),
            cash=q_money(balances.cash),
            positions_value=q_money(pv),
            deployable_capital=deployable_capital(nav, self.settings.cash_reserve_pct),
            reserve_target=q_money(nav * self.settings.cash_reserve_pct / 100),
            gas_eth=balances.gas_eth,
            gas_usd=q_money(balances.gas_eth * eth_usd) if eth_usd is not None else None,
            eth_usd=eth_usd,
            positions=detail,
            missing_prices=missing,
        )

    # ------------------------------------------------------------------ totals
    def totals(self) -> FundingTotals:
        t = FundingTotals()
        for kind, amount in self.session.execute(
            select(FundingEvent.kind, func.sum(FundingEvent.amount)).group_by(FundingEvent.kind)
        ).all():
            amt = D(amount or 0)
            if kind in ("BASE_CAPITAL", "DEMO_SEED"):
                t.base_capital += amt
            else:
                t.contributions += amt
        t.withdrawals = D(
            self.session.execute(
                select(func.coalesce(func.sum(WithdrawalEvent.amount), 0)).where(
                    WithdrawalEvent.status != "FAILED"
                )
            ).scalar_one()
        )
        eth, usd = self.session.execute(
            select(
                func.coalesce(func.sum(BlockchainTransaction.gas_cost_eth), 0),
                func.coalesce(func.sum(BlockchainTransaction.gas_cost_usd), 0),
            )
        ).one()
        t.cumulative_gas_eth = D(eth)
        t.cumulative_gas_usd = D(usd)
        return t

    def latest_snapshot(self) -> TreasurySnapshot | None:
        return self.session.execute(
            select(TreasurySnapshot).order_by(TreasurySnapshot.taken_at.desc()).limit(1)
        ).scalar_one_or_none()

    def take_snapshot(
        self, valuation: TreasuryValuation, books: dict[str, Book], taken_at: datetime | None = None
    ) -> TreasurySnapshot:
        taken_at = taken_at or datetime.now(UTC)
        totals = self.totals()
        prev = self.latest_snapshot()
        twr = Decimal(1)
        if prev is not None and D(prev.nav) > 0:
            flows = self._external_flows_between(prev.taken_at, taken_at)
            base = D(prev.nav) + flows
            twr = D(prev.twr_index) * (valuation.nav / base) if base > 0 else D(prev.twr_index)
        elif totals.net_external > 0:
            # first snapshot: everything contributed so far is treated as invested at inception
            twr = valuation.nav / totals.net_external
        realized = sum((b.realized_pnl for b in books.values()), ZERO)
        token_prices = {sym: D(d["token_price"]) for sym, d in valuation.positions.items()}
        unrealized = ZERO
        for b in books.values():
            for sym, pos in b.positions.items():
                if pos.quantity > 0:
                    unrealized += pos.unrealized_pnl(token_prices.get(sym, pos.avg_cost))
        snap = TreasurySnapshot(
            taken_at=taken_at,
            mode=self.mode,
            wallet_address=valuation.balances.wallet_address,
            nav=valuation.nav,
            cash_balance=valuation.cash,
            positions_value=valuation.positions_value,
            deployable_capital=valuation.deployable_capital,
            reserved_cash=valuation.reserve_target,
            gas_balance_eth=valuation.gas_eth,
            gas_balance_usd=valuation.gas_usd,
            realized_pnl=q_money(realized),
            unrealized_pnl=q_money(unrealized),
            cumulative_gas_eth=totals.cumulative_gas_eth,
            cumulative_gas_usd=totals.cumulative_gas_usd,
            base_capital=totals.base_capital,
            contributions_total=totals.contributions,
            withdrawals_total=totals.withdrawals,
            twr_index=twr,
            positions=valuation.positions,
        )
        self.session.add(snap)
        self.session.flush()
        return snap

    def _external_flows_between(self, start: datetime, end: datetime) -> Decimal:
        dep = D(
            self.session.execute(
                select(func.coalesce(func.sum(FundingEvent.amount), 0)).where(
                    FundingEvent.detected_at > start, FundingEvent.detected_at <= end
                )
            ).scalar_one()
        )
        wd = D(
            self.session.execute(
                select(func.coalesce(func.sum(WithdrawalEvent.amount), 0)).where(
                    WithdrawalEvent.created_at > start,
                    WithdrawalEvent.created_at <= end,
                    WithdrawalEvent.status != "FAILED",
                )
            ).scalar_one()
        )
        return dep - wd
