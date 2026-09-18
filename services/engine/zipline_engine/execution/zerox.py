"""ZeroXExecutionAdapter: live execution through the 0x Swap API v2 (Allowance Holder flow).

    GET {ZEROX_API_URL}/swap/allowance-holder/price   indicative
    GET {ZEROX_API_URL}/swap/allowance-holder/quote   firm quote + unsigned transaction
    headers: 0x-api-key, 0x-version: v2

0x provides RFQ-based Stock Token liquidity on Robinhood Chain (chain 4663). A quote is
never assumed to be a fill: the actual amounts are read back from the ERC-20 Transfer logs of
the confirmed receipt.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from zipline_engine.chain.rpc import ChainClient, checksum
from zipline_engine.chain.signer import LocalSigner
from zipline_engine.core.money import ZERO, D, from_wei, to_wei
from zipline_engine.db.enums import ExecutionMode, OrderStatus, Side, TxKind, TxStatus
from zipline_engine.execution.base import (
    ExecutionAdapter,
    ExecutionResult,
    Quote,
    TradeRequest,
    TxRecord,
)
from zipline_engine.logging_setup import redact

log = logging.getLogger(__name__)


class ZeroXError(RuntimeError):
    pass


def parse_quote(
    payload: dict[str, Any],
    request_side: Side,
    token_decimals: int,
    cash_decimals: int,
    quoted_at: datetime,
    ttl_sec: int,
) -> Quote:
    """Parse a v2 allowance-holder quote/price payload into a Quote."""
    liquidity = bool(payload.get("liquidityAvailable", True))
    sell_raw = int(payload.get("sellAmount") or 0)
    buy_raw = int(payload.get("buyAmount") or 0)
    min_buy = payload.get("minBuyAmount")
    tx = payload.get("transaction") or None
    issues = payload.get("issues") or {}
    allowance = issues.get("allowance")
    spender = allowance.get("spender") if isinstance(allowance, dict) else None
    allowance_required = (
        isinstance(allowance, dict) and int(allowance.get("actual") or 0) < sell_raw
    )
    if not liquidity or sell_raw <= 0 or buy_raw <= 0:
        price = ZERO
    elif request_side == Side.BUY:
        price = from_wei(sell_raw, cash_decimals) / from_wei(buy_raw, token_decimals)
    else:
        price = from_wei(buy_raw, cash_decimals) / from_wei(sell_raw, token_decimals)
    safe_tx = None
    if tx:
        data = str(tx.get("data") or "")
        safe_tx = {
            "to": tx.get("to"),
            "gas": tx.get("gas"),
            "gasPrice": tx.get("gasPrice"),
            "value": tx.get("value"),
            "data": data,
        }
    return Quote(
        provider="0x",
        sell_token=str(payload.get("sellToken", "")),
        buy_token=str(payload.get("buyToken", "")),
        sell_amount_raw=sell_raw,
        buy_amount_raw=buy_raw,
        min_buy_amount_raw=int(min_buy) if min_buy is not None else None,
        price=price,
        quoted_at=quoted_at,
        expires_at=quoted_at + timedelta(seconds=ttl_sec),
        gas_estimate=int(tx["gas"]) if tx and tx.get("gas") else None,
        gas_price_wei=int(tx["gasPrice"]) if tx and tx.get("gasPrice") else None,
        allowance_spender=spender,
        allowance_required=allowance_required,
        liquidity_available=liquidity,
        route={
            "fills": (payload.get("route") or {}).get("fills", []),
            "tokens": (payload.get("route") or {}).get("tokens", []),
            "fees": payload.get("fees"),
            "totalNetworkFee": payload.get("totalNetworkFee"),
            "zid": payload.get("zid"),
            "blockNumber": payload.get("blockNumber"),
            "tx_to": safe_tx["to"] if safe_tx else None,
            "tx_data_sha256": hashlib.sha256(safe_tx["data"].encode()).hexdigest()
            if safe_tx
            else None,
        },
        transaction=safe_tx,
        issues={
            k: v for k, v in issues.items() if k in ("allowance", "balance", "simulationIncomplete")
        },
    )


class ZeroXClient:
    def __init__(
        self, api_url: str, api_key: str, chain_id: int, client: httpx.Client | None = None
    ) -> None:
        if not api_key:
            raise ZeroXError("ZEROX_API_KEY is not set")
        self.api_url = api_url.rstrip("/")
        self.chain_id = chain_id
        self._client = client or httpx.Client(
            timeout=20, headers={"0x-api-key": api_key, "0x-version": "v2"}
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._client.get(f"{self.api_url}{path}", params=params)
        except httpx.HTTPError as e:
            raise ZeroXError(f"0x request failed: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ZeroXError(f"0x HTTP {r.status_code}: {redact(r.text[:300])}")
        try:
            return r.json()
        except ValueError as e:
            raise ZeroXError("0x returned non-JSON") from e

    def price(
        self,
        sell_token: str,
        buy_token: str,
        sell_amount_raw: int,
        taker: str | None,
        slippage_bps: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chainId": self.chain_id,
            "sellToken": sell_token,
            "buyToken": buy_token,
            "sellAmount": str(sell_amount_raw),
            "slippageBps": slippage_bps,
        }
        if taker:
            params["taker"] = taker
        return self._get("/swap/allowance-holder/price", params)

    def quote(
        self, sell_token: str, buy_token: str, sell_amount_raw: int, taker: str, slippage_bps: int
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chainId": self.chain_id,
            "sellToken": sell_token,
            "buyToken": buy_token,
            "sellAmount": str(sell_amount_raw),
            "taker": taker,
            "slippageBps": slippage_bps,
        }
        return self._get("/swap/allowance-holder/quote", params)


class ZeroXExecutionAdapter(ExecutionAdapter):
    name = "zerox"
    mode = ExecutionMode.LIVE

    def __init__(
        self,
        zerox: ZeroXClient,
        chain: ChainClient,
        signer: LocalSigner,
        *,
        slippage_bps: int,
        quote_ttl_sec: int,
        min_gas_eth: Decimal,
        receipt_timeout_sec: float = 180.0,
        probe_impact: bool = True,
    ) -> None:
        self.zerox = zerox
        self.chain = chain
        self.signer = signer
        self.slippage_bps = slippage_bps
        self.quote_ttl = quote_ttl_sec
        self.min_gas_eth = min_gas_eth
        self.receipt_timeout = receipt_timeout_sec
        self.probe_impact = probe_impact

    # ------------------------------------------------------------------ quoting
    def _sell_amount_raw(self, request: TradeRequest) -> int:
        if request.side == Side.BUY:
            return to_wei(request.notional, request.cash_decimals)
        return to_wei(request.quantity, request.token_decimals)

    def quote(self, request: TradeRequest) -> Quote:
        if not request.taker:
            raise ZeroXError("taker (EXECUTOR_ADDRESS) is required for a firm quote")
        self.chain.verify_chain()
        sell_raw = self._sell_amount_raw(request)
        now = datetime.now(UTC)
        payload = self.zerox.quote(
            request.sell_token, request.buy_token, sell_raw, request.taker, self.slippage_bps
        )
        q = parse_quote(
            payload,
            request.side,
            request.token_decimals,
            request.cash_decimals,
            now,
            self.quote_ttl,
        )
        if q.liquidity_available and self.probe_impact:
            q.price_impact_bps = self._price_impact(request, q, sell_raw)
        return q

    def _price_impact(self, request: TradeRequest, q: Quote, sell_raw: int) -> Decimal | None:
        """Adverse deviation of the full-size quote from a small indicative probe (1% of size)."""
        try:
            probe_raw = max(sell_raw // 100, 1)
            p = self.zerox.price(
                request.sell_token, request.buy_token, probe_raw, request.taker, self.slippage_bps
            )
            pq = parse_quote(
                p,
                request.side,
                request.token_decimals,
                request.cash_decimals,
                q.quoted_at,
                self.quote_ttl,
            )
            if not pq.liquidity_available or pq.price <= 0 or q.price <= 0:
                return None
            adverse = (
                (q.price / pq.price - 1) if request.side == Side.BUY else (pq.price / q.price - 1)
            )
            return max(adverse, ZERO) * Decimal(10_000)
        except ZeroXError as e:
            log.warning("price-impact probe failed: %s", e)
            return None

    def indicative(
        self,
        sell_token: str,
        buy_token: str,
        sell_amount_raw: int,
        side: Side,
        token_decimals: int,
        cash_decimals: int,
    ) -> Quote:
        payload = self.zerox.price(sell_token, buy_token, sell_amount_raw, None, self.slippage_bps)
        return parse_quote(
            payload, side, token_decimals, cash_decimals, datetime.now(UTC), self.quote_ttl
        )

    # ------------------------------------------------------------------ execution
    def execute(
        self,
        request: TradeRequest,
        quote: Quote,
        on_submitted: Callable[[TxRecord], None] | None = None,
    ) -> ExecutionResult:
        txs: list[TxRecord] = []
        try:
            self.chain.verify_chain()
            if quote.transaction is None or not quote.liquidity_available:
                return self._fail(txs, "quote has no transaction / liquidity unavailable")
            if quote.expires_at and datetime.now(UTC) > quote.expires_at:
                return self._fail(txs, "quote is stale")
            sender = checksum(self.signer.address)
            if request.taker and checksum(request.taker) != sender:
                return self._fail(txs, "signer address does not match EXECUTOR_ADDRESS")

            # allowance (exact amount, never unlimited)
            if quote.allowance_required and quote.allowance_spender:
                actual = self.chain.allowance_raw(quote.sell_token, sender, quote.allowance_spender)
                if actual < quote.sell_amount_raw:
                    rec = self._send(
                        self.chain.build_approve_tx(
                            quote.sell_token, quote.allowance_spender, quote.sell_amount_raw, sender
                        ),
                        TxKind.APPROVE,
                        on_submitted,
                    )
                    txs.append(rec)
                    if rec.status != TxStatus.CONFIRMED:
                        return self._fail(txs, f"approve failed: {rec.error or rec.status}")

            tx = quote.transaction
            swap_tx: dict[str, Any] = {
                "from": sender,
                "to": checksum(str(tx["to"])),
                "data": tx["data"],
                "value": int(tx.get("value") or 0),
                "chainId": self.chain.expected_chain_id,
            }
            rec = self._send(
                swap_tx,
                TxKind.SWAP,
                on_submitted,
                gas_hint=quote.gas_estimate,
                gas_price_hint=quote.gas_price_wei,
            )
            txs.append(rec)
            if rec.status != TxStatus.CONFIRMED:
                return self._fail(
                    txs,
                    f"swap {rec.status}: {rec.error or 'reverted'}",
                    tx_hash=rec.tx_hash,
                    block=rec.block_number,
                )

            receipt = self._last_receipt
            received_raw, spent_raw = self._settlement_amounts(receipt, request, sender)
            if request.side == Side.BUY:
                qty = from_wei(received_raw, request.token_decimals)
                notional = from_wei(spent_raw, request.cash_decimals)
            else:
                qty = from_wei(spent_raw, request.token_decimals)
                notional = from_wei(received_raw, request.cash_decimals)
            if qty <= 0 or notional <= 0:
                return self._fail(
                    txs,
                    "confirmed transaction but no settlement transfers found",
                    tx_hash=rec.tx_hash,
                    block=rec.block_number,
                )
            eff = notional / qty
            slip = (
                (eff / request.reference_price - 1) * Decimal(10_000)
                if request.reference_price
                else ZERO
            )
            if request.side == Side.SELL:
                slip = -slip
            gas_eth = sum((t.gas_cost_eth or ZERO for t in txs), ZERO)
            return ExecutionResult(
                status=OrderStatus.CONFIRMED,
                mode=self.mode,
                executed_quantity=qty,
                executed_notional=notional,
                effective_price=eff,
                slippage_bps=slip,
                price_impact_bps=quote.price_impact_bps,
                gas_used=sum(t.gas_used or 0 for t in txs),
                gas_cost_eth=gas_eth,
                tx_hash=rec.tx_hash,
                block_number=rec.block_number,
                transactions=txs,
            )
        except Exception as e:  # any unexpected error is a FAILED order, never a fabricated fill
            log.exception("live execution error")
            return self._fail(txs, f"{type(e).__name__}: {redact(str(e))[:300]}")

    _last_receipt: Any = None

    def _send(
        self,
        tx: dict[str, Any],
        kind: TxKind,
        on_submitted: Callable[[TxRecord], None] | None,
        gas_hint: int | None = None,
        gas_price_hint: int | None = None,
    ) -> TxRecord:
        sender = checksum(self.signer.address)
        tx = dict(tx)
        tx["nonce"] = self.chain.nonce(sender)
        try:
            estimated = self.chain.estimate_gas(
                {k: v for k, v in tx.items() if k in ("from", "to", "data", "value")}
            )
        except Exception as e:
            raise RuntimeError(f"gas estimation failed (would revert?): {type(e).__name__}") from e
        gas_limit = int(max(estimated, gas_hint or 0) * 1.2)
        gas_price = int(gas_price_hint or self.chain.gas_price())
        tx["gas"] = gas_limit
        tx["gasPrice"] = gas_price
        cost_eth = Decimal(gas_limit * gas_price) / Decimal(10) ** 18
        balance = self.chain.eth_balance(sender)
        if balance < cost_eth + self.min_gas_eth:
            raise RuntimeError(
                f"insufficient ETH for gas: balance {balance:.6f}, need {cost_eth + self.min_gas_eth:.6f}"
            )
        raw = self.signer.sign(tx)
        tx_hash = self.chain.send_raw_transaction(raw)
        rec = TxRecord(
            kind=kind,
            tx_hash=_hx(tx_hash),
            from_address=sender,
            to_address=str(tx["to"]),
            status=TxStatus.PENDING,
            nonce=tx["nonce"],
            gas_limit=gas_limit,
        )
        if on_submitted:
            on_submitted(rec)
        try:
            receipt = self.chain.wait_for_receipt(rec.tx_hash, timeout=self.receipt_timeout)
        except Exception as e:
            rec.status = TxStatus.DROPPED
            rec.error = f"no receipt within {self.receipt_timeout}s: {type(e).__name__}"
            return rec
        self._last_receipt = receipt
        rec.gas_used = int(receipt["gasUsed"])
        rec.effective_gas_price_wei = int(receipt.get("effectiveGasPrice", gas_price))
        rec.block_number = int(receipt["blockNumber"])
        rec.status = TxStatus.CONFIRMED if int(receipt["status"]) == 1 else TxStatus.REVERTED
        if rec.status == TxStatus.REVERTED:
            rec.error = "transaction reverted"
        return rec

    def _settlement_amounts(
        self, receipt: Any, request: TradeRequest, taker: str
    ) -> tuple[int, int]:
        received = sum(
            t.amount_raw
            for t in self.chain.transfers_in_receipt(receipt, request.buy_token)
            if checksum(t.recipient) == taker
        )
        spent = sum(
            t.amount_raw
            for t in self.chain.transfers_in_receipt(receipt, request.sell_token)
            if checksum(t.sender) == taker
        )
        return int(received), int(spent)

    def _fail(
        self, txs: list[TxRecord], error: str, tx_hash: str | None = None, block: int | None = None
    ) -> ExecutionResult:
        return ExecutionResult(
            status=OrderStatus.FAILED,
            mode=self.mode,
            error=redact(error),
            tx_hash=tx_hash,
            block_number=block,
            gas_cost_eth=sum((t.gas_cost_eth or ZERO for t in txs), ZERO) if txs else None,
            gas_used=sum(t.gas_used or 0 for t in txs) if txs else None,
            transactions=txs,
        )


def _hx(h: str) -> str:
    h = str(h)
    return h if h.startswith("0x") else "0x" + h


def probe_route(
    adapter: ZeroXExecutionAdapter,
    *,
    token_address: str,
    cash_token: str,
    cash_decimals: int,
    probe_notional: Decimal,
    reference_token_price: Decimal,
) -> tuple[bool, Decimal | None]:
    """Universe-time liquidity probe: is there a route, and how far is it from Robinhood's mid?"""
    q = adapter.indicative(
        cash_token,
        token_address,
        to_wei(probe_notional, cash_decimals),
        Side.BUY,
        18,
        cash_decimals,
    )
    if not q.liquidity_available or q.price <= 0:
        return False, None
    deviation = (
        abs(q.price / reference_token_price - 1) * Decimal(10_000)
        if reference_token_price > 0
        else None
    )
    return True, D(deviation) if deviation is not None else None
