"""Robinhood Chain RPC access through web3.py.

The client verifies ``eth_chainId`` against the configured chain on first use and refuses
to operate on any other network. Nothing here signs; see ``signer.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from zipline_engine.chain.abi import CHAINLINK_AGGREGATOR_V3_ABI, ERC20_ABI, UI_MULTIPLIER_ABI
from zipline_engine.core.money import from_wei
from zipline_engine.core.multiplier import multiplier_from_ui

log = logging.getLogger(__name__)


class WrongNetworkError(RuntimeError):
    pass


class ChainUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransferLog:
    tx_hash: str
    block_number: int
    sender: str
    recipient: str
    amount_raw: int
    log_index: int


def checksum(address: str) -> str:
    from web3 import Web3

    return Web3.to_checksum_address(address)


def is_address(address: str | None) -> bool:
    from web3 import Web3

    return bool(address) and Web3.is_address(address)


class ChainClient:
    def __init__(self, rpc_url: str, expected_chain_id: int, request_timeout: float = 20.0) -> None:
        if not rpc_url:
            raise ChainUnavailableError("RH_RPC_URL is not configured")
        self.rpc_url = rpc_url
        self.expected_chain_id = expected_chain_id
        self._timeout = request_timeout
        self._w3: Any = None
        self._verified_chain_id: int | None = None

    # ------------------------------------------------------------------ connection
    @property
    def w3(self) -> Any:
        if self._w3 is None:
            from web3 import Web3

            self._w3 = Web3(
                Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": self._timeout})
            )
        return self._w3

    def verify_chain(self) -> int:
        if self._verified_chain_id is not None:
            return self._verified_chain_id
        try:
            actual = int(self.w3.eth.chain_id)
        except Exception as e:
            raise ChainUnavailableError(f"RPC unreachable: {type(e).__name__}") from e
        if actual != self.expected_chain_id:
            raise WrongNetworkError(
                f"RPC reports chain id {actual}, expected {self.expected_chain_id} (Robinhood Chain)"
            )
        self._verified_chain_id = actual
        return actual

    def block_number(self) -> int:
        self.verify_chain()
        return int(self.w3.eth.block_number)

    # ------------------------------------------------------------------ reads
    def eth_balance(self, address: str) -> Decimal:
        self.verify_chain()
        return from_wei(self.w3.eth.get_balance(checksum(address)), 18)

    def has_code(self, address: str) -> bool:
        self.verify_chain()
        return len(self.w3.eth.get_code(checksum(address))) > 0

    def _erc20(self, token: str) -> Any:
        return self.w3.eth.contract(address=checksum(token), abi=ERC20_ABI + UI_MULTIPLIER_ABI)

    def erc20_decimals(self, token: str) -> int:
        self.verify_chain()
        return int(self._erc20(token).functions.decimals().call())

    def erc20_symbol(self, token: str) -> str:
        self.verify_chain()
        return str(self._erc20(token).functions.symbol().call())

    def erc20_balance_raw(self, token: str, holder: str) -> int:
        self.verify_chain()
        return int(self._erc20(token).functions.balanceOf(checksum(holder)).call())

    def erc20_balance(self, token: str, holder: str, decimals: int | None = None) -> Decimal:
        dec = self.erc20_decimals(token) if decimals is None else decimals
        return from_wei(self.erc20_balance_raw(token, holder), dec)

    def ui_multiplier(self, token: str) -> Decimal | None:
        """ERC-8056 multiplier as a ratio, or None if the token does not implement it."""
        self.verify_chain()
        try:
            raw = int(self._erc20(token).functions.uiMultiplier().call())
        except Exception:
            return None
        return multiplier_from_ui(raw)

    def allowance_raw(self, token: str, owner: str, spender: str) -> int:
        self.verify_chain()
        return int(
            self._erc20(token).functions.allowance(checksum(owner), checksum(spender)).call()
        )

    def chainlink_price(self, feed: str) -> tuple[Decimal, int]:
        """(price, updated_at_unix) from an AggregatorV3 feed."""
        self.verify_chain()
        c = self.w3.eth.contract(address=checksum(feed), abi=CHAINLINK_AGGREGATOR_V3_ABI)
        decimals = int(c.functions.decimals().call())
        _, answer, _, updated_at, _ = c.functions.latestRoundData().call()
        return from_wei(int(answer), decimals), int(updated_at)

    # ------------------------------------------------------------------ tx building
    def build_approve_tx(
        self, token: str, spender: str, amount_raw: int, sender: str
    ) -> dict[str, Any]:
        self.verify_chain()
        c = self._erc20(token)
        return c.functions.approve(checksum(spender), amount_raw).build_transaction(
            {"from": checksum(sender), "chainId": self.expected_chain_id}
        )

    def build_transfer_tx(
        self, token: str, to: str, amount_raw: int, sender: str
    ) -> dict[str, Any]:
        self.verify_chain()
        c = self._erc20(token)
        return c.functions.transfer(checksum(to), amount_raw).build_transaction(
            {"from": checksum(sender), "chainId": self.expected_chain_id}
        )

    def estimate_gas(self, tx: dict[str, Any]) -> int:
        self.verify_chain()
        return int(self.w3.eth.estimate_gas(tx))

    def gas_price(self) -> int:
        self.verify_chain()
        return int(self.w3.eth.gas_price)

    def nonce(self, address: str) -> int:
        self.verify_chain()
        return int(self.w3.eth.get_transaction_count(checksum(address), "pending"))

    def send_raw_transaction(self, raw: bytes) -> str:
        self.verify_chain()
        return self.w3.eth.send_raw_transaction(raw).hex()

    def wait_for_receipt(self, tx_hash: str, timeout: float = 180.0) -> Any:
        self.verify_chain()
        return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)

    # ------------------------------------------------------------------ logs
    def transfers_in_receipt(self, receipt: Any, token: str) -> list[TransferLog]:
        c = self._erc20(token)
        out: list[TransferLog] = []
        for ev in c.events.Transfer().process_receipt(
            receipt, errors=__import__("web3").logs.DISCARD
        ):
            out.append(
                TransferLog(
                    tx_hash=receipt["transactionHash"].hex(),
                    block_number=int(receipt["blockNumber"]),
                    sender=ev["args"]["from"],
                    recipient=ev["args"]["to"],
                    amount_raw=int(ev["args"]["value"]),
                    log_index=int(ev["logIndex"]),
                )
            )
        return out

    def transfers_to(
        self, token: str, recipient: str, from_block: int, to_block: int
    ) -> list[TransferLog]:
        """Incoming ERC-20 transfers of ``token`` to ``recipient`` in a block range (funding detection)."""
        self.verify_chain()
        c = self._erc20(token)
        logs = c.events.Transfer().get_logs(
            from_block=from_block, to_block=to_block, argument_filters={"to": checksum(recipient)}
        )
        return [
            TransferLog(
                tx_hash=lg["transactionHash"].hex(),
                block_number=int(lg["blockNumber"]),
                sender=lg["args"]["from"],
                recipient=lg["args"]["to"],
                amount_raw=int(lg["args"]["value"]),
                log_index=int(lg["logIndex"]),
            )
            for lg in logs
        ]


def normalize_hash(h: str) -> str:
    h = h.lower()
    return h if h.startswith("0x") else "0x" + h
