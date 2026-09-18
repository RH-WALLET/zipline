"""Treasury balance backends.

* ``OnchainTreasury``   reads the real wallet over RPC (source of truth in live/onchain mode)
* ``SimulatedTreasury`` DEMO MODE: database rows standing in for wallet balances
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from zipline_engine.chain.rpc import ChainClient
from zipline_engine.core.money import ZERO, D
from zipline_engine.db.models import Asset, SimulatedBalance

CASH_KEY = "__CASH__"
GAS_KEY = "__GAS_ETH__"


@dataclass
class TreasuryBalances:
    mode: str
    source: str
    wallet_address: str | None
    cash: Decimal
    positions: dict[str, Decimal]  # symbol -> raw token quantity
    gas_eth: Decimal
    fetched_at: datetime
    block_number: int | None = None
    unknown_tokens: list[str] = field(default_factory=list)


class SimulatedTreasury:
    mode = "simulated"

    def __init__(self, session: Session) -> None:
        self.session = session

    def _row(self, key: str) -> SimulatedBalance:
        row = self.session.execute(
            select(SimulatedBalance).where(SimulatedBalance.symbol == key)
        ).scalar_one_or_none()
        if row is None:
            row = SimulatedBalance(symbol=key, quantity=ZERO)
            self.session.add(row)
            self.session.flush()
        return row

    def read_balances(self, assets: list[Asset]) -> TreasuryBalances:
        rows = self.session.execute(select(SimulatedBalance)).scalars().all()
        by = {r.symbol: D(r.quantity) for r in rows}
        positions = {s: q for s, q in by.items() if s not in (CASH_KEY, GAS_KEY) and q > 0}
        return TreasuryBalances(
            mode=self.mode,
            source="simulated_db",
            wallet_address=None,
            cash=by.get(CASH_KEY, ZERO),
            positions=dict(sorted(positions.items())),
            gas_eth=by.get(GAS_KEY, ZERO),
            fetched_at=datetime.now(UTC),
        )

    def is_empty(self) -> bool:
        return not self.session.execute(select(SimulatedBalance.id).limit(1)).first()

    def deposit_cash(self, amount: Decimal) -> None:
        row = self._row(CASH_KEY)
        row.quantity = D(row.quantity) + amount

    def withdraw_cash(self, amount: Decimal) -> None:
        row = self._row(CASH_KEY)
        if D(row.quantity) < amount:
            raise ValueError("insufficient simulated cash")
        row.quantity = D(row.quantity) - amount

    def set_gas(self, eth: Decimal) -> None:
        self._row(GAS_KEY).quantity = eth

    def apply_swap(
        self, symbol: str, side: str, quantity: Decimal, notional: Decimal, gas_eth: Decimal = ZERO
    ) -> None:
        cash = self._row(CASH_KEY)
        pos = self._row(symbol)
        gas = self._row(GAS_KEY)
        if side == "BUY":
            if D(cash.quantity) < notional:
                raise ValueError("insufficient simulated cash for buy")
            cash.quantity = D(cash.quantity) - notional
            pos.quantity = D(pos.quantity) + quantity
        else:
            if D(pos.quantity) < quantity - Decimal("1e-12"):
                raise ValueError("insufficient simulated position for sell")
            pos.quantity = max(D(pos.quantity) - quantity, ZERO)
            cash.quantity = D(cash.quantity) + notional
        gas.quantity = max(D(gas.quantity) - gas_eth, ZERO)
        self.session.flush()


class OnchainTreasury:
    mode = "onchain"

    def __init__(
        self, chain: ChainClient, wallet_address: str, cash_token: str, chain_id: int
    ) -> None:
        self.chain = chain
        self.wallet = wallet_address
        self.cash_token = cash_token
        self.chain_id = chain_id
        self._cash_decimals: int | None = None

    def cash_decimals(self) -> int:
        if self._cash_decimals is None:
            self._cash_decimals = self.chain.erc20_decimals(self.cash_token)
        return self._cash_decimals

    def read_balances(self, assets: list[Asset]) -> TreasuryBalances:
        self.chain.verify_chain()
        block = self.chain.block_number()
        cash = self.chain.erc20_balance(self.cash_token, self.wallet, self.cash_decimals())
        positions: dict[str, Decimal] = {}
        for asset in assets:
            dep = next((d for d in asset.deployments if d.chain_id == self.chain_id), None)
            if dep is None:
                continue
            qty = self.chain.erc20_balance(dep.contract_address, self.wallet, dep.decimals or 18)
            if qty > 0:
                positions[asset.symbol] = qty
        return TreasuryBalances(
            mode=self.mode,
            source="rpc",
            wallet_address=self.wallet,
            cash=cash,
            positions=dict(sorted(positions.items())),
            gas_eth=self.chain.eth_balance(self.wallet),
            fetched_at=datetime.now(UTC),
            block_number=block,
        )
