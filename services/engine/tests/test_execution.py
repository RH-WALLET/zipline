"""Execution: quote parsing, validators, adapter failure modes, chain-id protection, redaction."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from zipline_engine.chain.rpc import ChainClient, WrongNetworkError
from zipline_engine.config import Settings
from zipline_engine.core.money import to_wei
from zipline_engine.db.enums import OrderStatus, Side, TxKind, TxStatus
from zipline_engine.execution import validators
from zipline_engine.execution.base import Quote, TradeRejected, TradeRequest
from zipline_engine.execution.dryrun import DryRunExecutionAdapter
from zipline_engine.execution.zerox import ZeroXExecutionAdapter, parse_quote
from zipline_engine.logging_setup import RedactionFilter, configure_logging
from zipline_engine.robinhood.pricing import RefPrice

D = Decimal
TOKEN = "0xd0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC"
CASH = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
TAKER = "0x1111111111111111111111111111111111111111"


def ref(
    symbol: str = "NVDA",
    mid: str = "200",
    mult: str = "1",
    age_sec: int = 5,
    source: str = "robinhood_api",
) -> RefPrice:
    now = datetime.now(UTC)
    m = D(mid)
    return RefPrice(
        symbol,
        1,
        m - D("0.02"),
        m + D("0.02"),
        m,
        D(mult),
        now - timedelta(seconds=age_sec),
        now,
        source,
        False,
        False,
    )


def request(
    side: Side = Side.BUY, notional: str = "100", qty: str = "0.5", ref_price: str = "200"
) -> TradeRequest:
    return TradeRequest(
        "NVDA", 1, side, D(qty), D(notional), D(ref_price), TOKEN, 18, CASH, 6, TAKER
    )


def zerox_payload(
    sell_amount: int, buy_amount: int, liquidity: bool = True, allowance_actual: int = 0
) -> dict[str, Any]:
    if not liquidity:
        return {"liquidityAvailable": False, "zid": "0xabc"}
    return {
        "blockNumber": "123456",
        "buyAmount": str(buy_amount),
        "buyToken": TOKEN,
        "sellAmount": str(sell_amount),
        "sellToken": CASH,
        "minBuyAmount": str(int(buy_amount * 0.99)),
        "liquidityAvailable": True,
        "issues": {
            "allowance": {
                "actual": str(allowance_actual),
                "spender": "0x2222222222222222222222222222222222222222",
            },
            "balance": None,
            "simulationIncomplete": False,
        },
        "route": {
            "fills": [{"from": CASH, "to": TOKEN, "source": "RFQ", "proportionBps": "10000"}],
            "tokens": [],
        },
        "fees": {"zeroExFee": None},
        "totalNetworkFee": "1000",
        "transaction": {
            "to": "0x3333333333333333333333333333333333333333",
            "data": "0xdeadbeef",
            "gas": "210000",
            "gasPrice": "100000000",
            "value": "0",
        },
        "zid": "0xzid",
    }


# ------------------------------------------------------------------ quote parsing


def test_parse_quote_buy_and_allowance() -> None:
    q = parse_quote(
        zerox_payload(to_wei(D(100), 6), to_wei(D("0.5"), 18)),
        Side.BUY,
        18,
        6,
        datetime.now(UTC),
        30,
    )
    assert q.price == D(200)
    assert q.allowance_required is True and q.allowance_spender.startswith("0x2222")
    assert q.transaction is not None and q.transaction["to"].startswith("0x3333")
    assert q.route["tx_data_sha256"]
    assert q.quantity(Side.BUY, 18, 6) == D("0.5") and q.notional(Side.BUY, 18, 6) == D(100)


def test_parse_quote_no_liquidity() -> None:
    q = parse_quote(zerox_payload(0, 0, liquidity=False), Side.BUY, 18, 6, datetime.now(UTC), 30)
    assert q.liquidity_available is False and q.price == 0 and q.transaction is None


def test_parse_quote_allowance_sufficient() -> None:
    q = parse_quote(
        zerox_payload(1000, 5, allowance_actual=10**30), Side.BUY, 18, 6, datetime.now(UTC), 30
    )
    assert q.allowance_required is False


# ------------------------------------------------------------------ validators


def test_validate_quote_slippage_rejection() -> None:
    q = parse_quote(
        zerox_payload(to_wei(D(100), 6), to_wei(D("0.48"), 18)),
        Side.BUY,
        18,
        6,
        datetime.now(UTC),
        30,
    )  # 208.33 vs 200 ref = +416 bps
    with pytest.raises(TradeRejected) as e:
        validators.validate_quote(
            q, request(), max_slippage_bps=100, max_price_impact_bps=150, quote_staleness_sec=30
        )
    assert e.value.code == "EXCESSIVE_SLIPPAGE"


def test_validate_quote_price_impact_rejection() -> None:
    q = parse_quote(
        zerox_payload(to_wei(D(100), 6), to_wei(D("0.5"), 18)),
        Side.BUY,
        18,
        6,
        datetime.now(UTC),
        30,
    )
    q.price_impact_bps = D(400)
    with pytest.raises(TradeRejected) as e:
        validators.validate_quote(
            q, request(), max_slippage_bps=100, max_price_impact_bps=150, quote_staleness_sec=30
        )
    assert e.value.code == "EXCESSIVE_PRICE_IMPACT"


def test_validate_quote_stale_and_liquidity_and_token_mismatch() -> None:
    q = parse_quote(
        zerox_payload(to_wei(D(100), 6), to_wei(D("0.5"), 18)),
        Side.BUY,
        18,
        6,
        datetime.now(UTC) - timedelta(seconds=90),
        30,
    )
    with pytest.raises(TradeRejected) as e:
        validators.validate_quote(
            q, request(), max_slippage_bps=100, max_price_impact_bps=150, quote_staleness_sec=30
        )
    assert e.value.code == "STALE_QUOTE"
    q2 = parse_quote(zerox_payload(0, 0, liquidity=False), Side.BUY, 18, 6, datetime.now(UTC), 30)
    with pytest.raises(TradeRejected) as e:
        validators.validate_quote(
            q2, request(), max_slippage_bps=100, max_price_impact_bps=150, quote_staleness_sec=30
        )
    assert e.value.code == "NO_LIQUIDITY"
    q3 = parse_quote(
        zerox_payload(to_wei(D(100), 6), to_wei(D("0.5"), 18)),
        Side.BUY,
        18,
        6,
        datetime.now(UTC),
        30,
    )
    q3.buy_token = "0x4444444444444444444444444444444444444444"
    with pytest.raises(TradeRejected) as e:
        validators.validate_quote(
            q3, request(), max_slippage_bps=100, max_price_impact_bps=150, quote_staleness_sec=30
        )
    assert e.value.code == "UNKNOWN_TOKEN"


def test_validate_token_addresses() -> None:
    validators.validate_token_addresses(request(), TOKEN, CASH)
    with pytest.raises(TradeRejected):
        validators.validate_token_addresses(
            request(), "0x9999999999999999999999999999999999999999", CASH
        )
    with pytest.raises(TradeRejected):
        validators.validate_token_addresses(request(), TOKEN, TOKEN)


def test_validate_asset_status_halted_and_ineligible() -> None:
    with pytest.raises(TradeRejected) as e:
        validators.validate_asset_status(
            symbol="NVDA",
            eligible=True,
            hold_only=False,
            halted=True,
            side=Side.BUY,
            verified_onchain=True,
            require_verified=True,
        )
    assert e.value.code == "HALTED"
    with pytest.raises(TradeRejected) as e:
        validators.validate_asset_status(
            symbol="NVDA",
            eligible=False,
            hold_only=False,
            halted=False,
            side=Side.BUY,
            verified_onchain=True,
            require_verified=True,
        )
    assert e.value.code == "UNSUPPORTED_TOKEN"
    # hold-only assets may still be SOLD (e.g. leaving the universe) but never bought
    validators.validate_asset_status(
        symbol="NVDA",
        eligible=False,
        hold_only=True,
        halted=False,
        side=Side.SELL,
        verified_onchain=True,
        require_verified=True,
    )
    with pytest.raises(TradeRejected) as e:
        validators.validate_asset_status(
            symbol="NVDA",
            eligible=True,
            hold_only=False,
            halted=False,
            side=Side.BUY,
            verified_onchain=None,
            require_verified=True,
        )
    assert e.value.code == "NON_STOCK_TOKEN"


def test_validate_reference_price_staleness() -> None:
    validators.validate_reference_price(ref(age_sec=10), "NVDA", 120)
    with pytest.raises(TradeRejected) as e:
        validators.validate_reference_price(ref(age_sec=1000), "NVDA", 120)
    assert e.value.code == "STALE_PRICE"
    with pytest.raises(TradeRejected):
        validators.validate_reference_price(ref(source="last_close"), "NVDA", 120)
    with pytest.raises(TradeRejected):
        validators.validate_reference_price(None, "NVDA", 120)


def test_validate_balance_gas_and_size() -> None:
    with pytest.raises(TradeRejected) as e:
        validators.validate_balance(
            request(notional="500"), treasury_cash=D(100), treasury_position=D(0)
        )
    assert e.value.code == "INSUFFICIENT_BALANCE"
    with pytest.raises(TradeRejected):
        validators.validate_balance(
            request(Side.SELL, qty="3"), treasury_cash=D(100), treasury_position=D(2)
        )
    with pytest.raises(TradeRejected) as e:
        validators.validate_gas(D("0.0001"), D("0.002"), live=True)
    assert e.value.code == "INSUFFICIENT_GAS"
    validators.validate_gas(D(0), D("0.002"), live=False)  # dry-run never needs gas
    with pytest.raises(TradeRejected) as e:
        validators.validate_order_size(
            request(notional="2000"),
            treasury_nav=D(10000),
            max_order_pct=D(10),
            turnover_today=D(0),
            max_turnover_pct=D(50),
        )
    assert e.value.code == "OVERSIZED_ORDER"
    with pytest.raises(TradeRejected) as e:
        validators.validate_order_size(
            request(notional="500"),
            treasury_nav=D(10000),
            max_order_pct=D(10),
            turnover_today=D(4800),
            max_turnover_pct=D(50),
        )
    assert e.value.code == "DAILY_TURNOVER"


# ------------------------------------------------------------------ dry run never touches the chain


def test_dry_run_adapter_fills_at_spread_and_has_no_transaction() -> None:
    adapter = DryRunExecutionAdapter({"NVDA": ref()})
    req = request(notional="100", ref_price="200")
    q = adapter.quote(req)
    assert q.price == D("200.02")  # ask
    res = adapter.execute(req, q)
    assert res.status == OrderStatus.DRY_RUN_FILLED
    assert res.tx_hash is None and res.transactions == [] and res.gas_cost_eth is None
    assert res.executed_notional == D(100)
    assert res.slippage_bps > 0


# ------------------------------------------------------------------ live adapter with a fake chain


class FakeChain:
    def __init__(
        self,
        *,
        chain_id: int = 4663,
        receipt_status: int = 1,
        eth: str = "1",
        transfers: list[tuple[str, str, str, int]] | None = None,
    ) -> None:
        self.expected_chain_id = 4663
        self._chain_id = chain_id
        self.receipt_status = receipt_status
        self.eth = D(eth)
        self.sent: list[bytes] = []
        self.transfers = transfers or []

    def verify_chain(self) -> int:
        if self._chain_id != self.expected_chain_id:
            raise WrongNetworkError("wrong network")
        return self._chain_id

    def allowance_raw(self, *a: Any) -> int:
        return 10**30

    def nonce(self, a: str) -> int:
        return 7

    def estimate_gas(self, tx: dict[str, Any]) -> int:
        return 100000

    def gas_price(self) -> int:
        return 10**8

    def eth_balance(self, a: str) -> Decimal:
        return self.eth

    def send_raw_transaction(self, raw: bytes) -> str:
        self.sent.append(raw)
        return "ab" * 32

    def wait_for_receipt(self, h: str, timeout: float = 0) -> dict[str, Any]:
        return {
            "status": self.receipt_status,
            "gasUsed": 90000,
            "effectiveGasPrice": 10**8,
            "blockNumber": 555,
            "transactionHash": SimpleNamespace(hex=lambda: "0x" + "ab" * 32),
        }

    def transfers_in_receipt(self, receipt: Any, token: str) -> list[Any]:
        return [
            SimpleNamespace(recipient=r, sender=s, amount_raw=amt)
            for (tok, s, r, amt) in self.transfers
            if tok.lower() == token.lower()
        ]


class FakeSigner:
    address = TAKER

    def sign(self, tx: dict[str, Any]) -> bytes:
        assert "gasPrice" in tx and tx["chainId"] == 4663
        return b"signed"


def make_adapter(chain: FakeChain) -> ZeroXExecutionAdapter:
    return ZeroXExecutionAdapter(
        SimpleNamespace(),
        chain,
        FakeSigner(),
        slippage_bps=100,
        quote_ttl_sec=30,
        min_gas_eth=D("0.002"),
        probe_impact=False,
    )  # type: ignore[arg-type]


def live_quote(allowance_actual: int = 10**30) -> Quote:
    return parse_quote(
        zerox_payload(to_wei(D(100), 6), to_wei(D("0.5"), 18), allowance_actual=allowance_actual),
        Side.BUY,
        18,
        6,
        datetime.now(UTC),
        30,
    )


def test_live_execution_reads_actual_fill_from_transfer_logs() -> None:
    chain = FakeChain(
        transfers=[
            (TOKEN, "0x3333333333333333333333333333333333333333", TAKER, to_wei(D("0.49"), 18)),
            (CASH, TAKER, "0x3333333333333333333333333333333333333333", to_wei(D(100), 6)),
        ]
    )
    res = make_adapter(chain).execute(request(), live_quote())
    assert res.status == OrderStatus.CONFIRMED
    assert res.executed_quantity == D("0.49") and res.executed_notional == D(
        100
    )  # quote said 0.50: never assume quote == fill
    assert res.effective_price.quantize(D("0.01")) == D("204.08")
    assert res.tx_hash == "0x" + "ab" * 32 and res.block_number == 555
    assert res.gas_cost_eth == D(90000 * 10**8) / D(10) ** 18
    assert len(chain.sent) == 1


def test_live_execution_reverted_is_failed_not_filled() -> None:
    chain = FakeChain(receipt_status=0)
    res = make_adapter(chain).execute(request(), live_quote())
    assert res.status == OrderStatus.FAILED
    assert res.executed_quantity is None
    assert res.transactions[0].status == TxStatus.REVERTED and res.tx_hash == "0x" + "ab" * 32


def test_live_execution_insufficient_gas_never_broadcasts() -> None:
    chain = FakeChain(eth="0.0001")
    res = make_adapter(chain).execute(request(), live_quote())
    assert res.status == OrderStatus.FAILED and "insufficient ETH" in (res.error or "")
    assert chain.sent == []


def test_live_execution_wrong_chain_refuses() -> None:
    chain = FakeChain(chain_id=42161)
    res = make_adapter(chain).execute(request(), live_quote())
    assert res.status == OrderStatus.FAILED and "WrongNetworkError" in (res.error or "")
    assert chain.sent == []


def test_live_execution_stale_quote_refuses() -> None:
    chain = FakeChain()
    q = live_quote()
    q.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    res = make_adapter(chain).execute(request(), q)
    assert res.status == OrderStatus.FAILED and chain.sent == []


def test_live_execution_approves_exact_amount_when_needed() -> None:
    class Chain(FakeChain):
        def __init__(self) -> None:
            super().__init__(
                transfers=[
                    (
                        TOKEN,
                        "0x3333333333333333333333333333333333333333",
                        TAKER,
                        to_wei(D("0.5"), 18),
                    ),
                    (CASH, TAKER, "0x3333333333333333333333333333333333333333", to_wei(D(100), 6)),
                ]
            )
            self.approvals: list[int] = []

        def allowance_raw(self, *a: Any) -> int:
            return 0

        def build_approve_tx(
            self, token: str, spender: str, amount_raw: int, sender: str
        ) -> dict[str, Any]:
            self.approvals.append(amount_raw)
            return {"from": sender, "to": token, "data": "0x095ea7b3", "value": 0, "chainId": 4663}

    chain = Chain()
    res = make_adapter(chain).execute(request(), live_quote(allowance_actual=0))
    assert res.status == OrderStatus.CONFIRMED
    assert chain.approvals == [to_wei(D(100), 6)]  # exact, never unlimited
    assert [t.kind for t in res.transactions] == [TxKind.APPROVE, TxKind.SWAP]


def test_chain_client_rejects_wrong_network() -> None:
    client = ChainClient("http://localhost:1", 4663)
    client._w3 = SimpleNamespace(eth=SimpleNamespace(chain_id=1))
    with pytest.raises(WrongNetworkError):
        client.verify_chain()


# ------------------------------------------------------------------ secrets


def test_private_key_redaction_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    key = "0x" + "ab" * 32
    s = Settings(
        executor_private_key=key,
        zerox_api_key="zx-secret-key-123",
        admin_token="admin-secret-1",
        _env_file=None,
    )  # type: ignore[call-arg]
    f = configure_logging("INFO", s.secret_values())
    assert (
        f.redact(f"key={key} raw={key[2:]} zx=zx-secret-key-123")
        == "key=[REDACTED] raw=[REDACTED] zx=[REDACTED]"
    )
    public = s.public_dict()
    assert (
        key not in str(public)
        and "zx-secret-key-123" not in str(public)
        and "admin-secret-1" not in str(public)
    )
    assert (
        "private" not in " ".join(public.keys()).lower() or public.get("signer_configured") is True
    )
    assert repr(s.executor_private_key) == "SecretStr('**********')"
    assert RedactionFilter([key]).redact("nothing here") == "nothing here"
    logging.getLogger().handlers.clear()


def test_signer_repr_never_reveals_key() -> None:
    from zipline_engine.chain.signer import LocalSigner, SignerNotConfiguredError

    key = "0x" + "11" * 32
    signer = LocalSigner(key)
    assert key not in repr(signer) and key[2:] not in repr(signer)
    assert signer.address.startswith("0x")
    with pytest.raises(SignerNotConfiguredError):
        LocalSigner("")
    with pytest.raises(SignerNotConfiguredError):
        LocalSigner("not-a-key")
