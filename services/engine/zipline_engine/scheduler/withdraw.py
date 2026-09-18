"""Operator withdrawals: reduce treasury capital explicitly, never as a loss."""

from __future__ import annotations

import logging
from decimal import Decimal

from zipline_engine.core.money import D, q_money
from zipline_engine.db.enums import TxKind, TxStatus
from zipline_engine.db.models import BlockchainTransaction, WithdrawalEvent
from zipline_engine.runtime import Runtime, live_blockers
from zipline_engine.scheduler.cycle import mark_and_save, observe_market

log = logging.getLogger(__name__)


def record_withdrawal(
    rt: Runtime,
    amount: Decimal,
    *,
    to_address: str | None,
    tx_hash: str | None,
    note: str,
    broadcast: bool,
) -> WithdrawalEvent:
    market = observe_market(rt, refresh_universe=False)
    loaded = rt.repo.load()
    if amount > market.valuation.cash:
        raise ValueError(
            f"withdrawal {amount} exceeds treasury cash {market.valuation.cash}; liquidate positions first"
        )
    sleeve_cash = sum((b.cash for b in loaded.books.values()), Decimal(0))
    buffer = market.valuation.cash - sleeve_cash
    dealloc = rt.allocator.deallocate(amount, loaded.books, buffer)
    status = "RECORDED"
    if rt.simulated is not None:
        rt.simulated.withdraw_cash(amount)
        status = "SIMULATED"
    elif broadcast:
        tx_hash = _broadcast_transfer(rt, amount, to_address)
        status = "CONFIRMED"
    ev = rt.funding.record_withdrawal(
        amount, to_address, tx_hash, dealloc, note=note, status=status
    )
    post = observe_market(rt, refresh_universe=False)
    mark_and_save(rt, loaded, post, None, snapshot=True)
    rt.reconciler.run(
        loaded.books,
        post.balances,
        post.token_prices,
        nav=post.valuation.nav,
        reserve_target=post.valuation.reserve_target,
        trigger="withdrawal",
    )
    rt.session.flush()
    return ev


def _broadcast_transfer(rt: Runtime, amount: Decimal, to_address: str | None) -> str:
    """Sign and send an ERC-20 transfer of the cash token from the treasury (live mode only)."""
    if not to_address:
        raise ValueError("to_address is required for an onchain withdrawal")
    problems = live_blockers(rt)
    if problems:
        raise RuntimeError("withdrawal blocked: " + "; ".join(problems))
    from zipline_engine.chain.rpc import checksum
    from zipline_engine.chain.signer import LocalSigner
    from zipline_engine.core.money import to_wei

    assert rt.chain is not None
    signer = LocalSigner(rt.settings.executor_private_key.get_secret_value())
    sender = checksum(signer.address)
    decimals = rt.chain.erc20_decimals(rt.settings.cash_token_address)
    tx = rt.chain.build_transfer_tx(
        rt.settings.cash_token_address, to_address, to_wei(amount, decimals), sender
    )
    tx["nonce"] = rt.chain.nonce(sender)
    tx["gas"] = int(
        rt.chain.estimate_gas({k: v for k, v in tx.items() if k in ("from", "to", "data", "value")})
        * 1.2
    )
    tx["gasPrice"] = rt.chain.gas_price()
    tx_hash = rt.chain.send_raw_transaction(signer.sign(tx))
    receipt = rt.chain.wait_for_receipt(tx_hash)
    rec = BlockchainTransaction(
        order_id=None,
        kind=str(TxKind.WITHDRAWAL),
        chain_id=rt.settings.chain_id,
        tx_hash=tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash,
        from_address=sender,
        to_address=checksum(to_address),
        nonce=tx["nonce"],
        gas_limit=tx["gas"],
        gas_used=int(receipt["gasUsed"]),
        effective_gas_price_wei=D(int(receipt.get("effectiveGasPrice", tx["gasPrice"]))),
        block_number=int(receipt["blockNumber"]),
        status=str(TxStatus.CONFIRMED if int(receipt["status"]) == 1 else TxStatus.REVERTED),
    )
    gas_used = int(receipt["gasUsed"])
    gas_price = int(receipt.get("effectiveGasPrice", tx["gasPrice"]))
    rec.gas_cost_eth = q_money(Decimal(gas_used * gas_price) / Decimal(10) ** 18)
    rt.session.add(rec)
    rt.session.flush()
    if rec.status != str(TxStatus.CONFIRMED):
        raise RuntimeError(f"withdrawal transaction reverted: {rec.tx_hash}")
    return rec.tx_hash
