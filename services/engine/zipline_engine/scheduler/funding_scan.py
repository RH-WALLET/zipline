"""Detect incoming cash-token transfers to the treasury wallet (onchain mode) and record them."""

from __future__ import annotations

import logging

from sqlalchemy import select

from zipline_engine.core.money import from_wei
from zipline_engine.core.system import get_state
from zipline_engine.db.enums import FundingKind
from zipline_engine.db.models import BlockchainTransaction
from zipline_engine.runtime import Runtime
from zipline_engine.treasury.backends import OnchainTreasury

log = logging.getLogger(__name__)

MAX_BLOCK_SPAN = 5000


def scan_funding(rt: Runtime) -> int:
    """Returns the number of new FundingEvents. No-op for the simulated treasury."""
    if not isinstance(rt.backend, OnchainTreasury):
        return 0
    chain = rt.backend.chain
    st = get_state(rt.session)
    meta = dict(st.meta or {})
    head = chain.block_number()
    start = int(meta.get("last_funding_block") or head) + 1
    if start > head:
        return 0
    end = min(head, start + MAX_BLOCK_SPAN)
    our_txs = {
        h.lower() for (h,) in rt.session.execute(select(BlockchainTransaction.tx_hash)).all()
    }
    known = {h.lower() for h in rt.funding.known_tx_hashes()}
    decimals = rt.backend.cash_decimals()
    n = 0
    for lg in chain.transfers_to(
        rt.settings.cash_token_address, rt.settings.executor_address, start, end
    ):
        h = lg.tx_hash.lower()
        if h in our_txs or h in known:
            continue  # proceeds of our own swaps are not contributions
        amount = from_wei(lg.amount_raw, decimals)
        if amount <= 0:
            continue
        rt.funding.record_funding(
            FundingKind.CONTRIBUTION,
            amount,
            tx_hash=lg.tx_hash,
            from_address=lg.sender,
            block_number=lg.block_number,
            note="detected ERC-20 transfer to treasury",
        )
        n += 1
    meta["last_funding_block"] = end
    st.meta = meta
    rt.session.flush()
    return n
