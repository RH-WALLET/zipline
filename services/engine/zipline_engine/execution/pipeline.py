"""ExecutionPipeline: net external orders -> validated quotes -> (dry-run | onchain) fills -> books.

Live flow (ZeroXExecutionAdapter), per order:
  1 net target change   2 required trade      3 executable quote   4 token addresses
  5 Stock Token status  6 allowance           7 treasury balance   8 treasury-relative limits
  9 slippage           10 price impact       11 gas estimate      12 sign locally
 13 broadcast          14 receipt            15 record actuals    16 reconcile treasury
 17 attribute to sleeves

A failed transaction is recorded as FAILED with its hash; a fill is never fabricated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from zipline_engine.accounting.books import Book, InsufficientCashError
from zipline_engine.accounting.netting import NetOrder, Participation, split_pro_rata
from zipline_engine.accounting.repository import BookRepository
from zipline_engine.config import Settings
from zipline_engine.core.money import ZERO, D, q_money
from zipline_engine.core.system import (
    add_turnover,
    get_state,
    record_failed_tx,
    reset_failures,
    turnover_today,
)
from zipline_engine.db.enums import (
    EventLevel,
    EventType,
    ExecutionMode,
    FillKind,
    OrderStatus,
    Side,
    TxStatus,
)
from zipline_engine.db.models import (
    Asset,
    BlockchainTransaction,
    ExecutionOrder,
    ExecutionQuote,
    Strategy,
)
from zipline_engine.events.bus import EventBus
from zipline_engine.execution import validators
from zipline_engine.execution.base import (
    ExecutionAdapter,
    ExecutionResult,
    Quote,
    TradeRejected,
    TradeRequest,
    TxRecord,
)
from zipline_engine.robinhood.pricing import RefPrice
from zipline_engine.treasury.backends import SimulatedTreasury, TreasuryBalances

log = logging.getLogger(__name__)


@dataclass
class _RunState:
    cash: Decimal
    positions: dict[str, Decimal]


@dataclass
class ExecutionSummary:
    submitted: int = 0
    filled: int = 0
    rejected: int = 0
    failed: int = 0
    gross_filled_notional: Decimal = ZERO
    paused: bool = False


class ExecutionPipeline:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        events: EventBus,
        adapter: ExecutionAdapter,
        repo: BookRepository,
        *,
        simulated: SimulatedTreasury | None,
        eth_usd: Decimal | None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.events = events
        self.adapter = adapter
        self.repo = repo
        self.simulated = simulated
        self.eth_usd = eth_usd
        self.live = adapter.mode == ExecutionMode.LIVE

    # ------------------------------------------------------------------ ids
    def _next_local_id(self) -> str:
        n = int(self.session.execute(select(func.count(ExecutionOrder.id))).scalar_one()) + 1
        prefix = "ord" if self.live else "dry"
        return f"{prefix}-{n:06d}"

    # ------------------------------------------------------------------ main
    def run(
        self,
        *,
        cycle_id: int | None,
        session_date: date,
        orders: list[NetOrder],
        books: dict[str, Book],
        strategies: dict[str, Strategy],
        asset_by_symbol: dict[str, Asset],
        prices: dict[str, RefPrice],
        treasury: TreasuryBalances,
        treasury_nav: Decimal,
        hold_only: set[str],
    ) -> ExecutionSummary:
        summary = ExecutionSummary()
        state = _RunState(cash=D(treasury.cash), positions=dict(treasury.positions))
        # sells first so buys are funded
        sells = sorted((o for o in orders if o.side == Side.SELL), key=lambda o: o.symbol)
        buys = sorted((o for o in orders if o.side == Side.BUY), key=lambda o: o.symbol)
        for order in sells:
            if self._paused(order, cycle_id, summary):
                return summary
            self._process(
                order,
                state,
                cycle_id,
                session_date,
                books,
                strategies,
                asset_by_symbol,
                prices,
                treasury,
                treasury_nav,
                hold_only,
                summary,
            )
        # sells that were rejected or failed did not raise cash: trim buys to what each sleeve can pay
        buys = trim_buys_to_sleeve_cash(buys, books, self.settings)
        for order in buys:
            if self._paused(order, cycle_id, summary):
                return summary
            self._process(
                order,
                state,
                cycle_id,
                session_date,
                books,
                strategies,
                asset_by_symbol,
                prices,
                treasury,
                treasury_nav,
                hold_only,
                summary,
            )
        return summary

    def _paused(self, order: NetOrder, cycle_id: int | None, summary: ExecutionSummary) -> bool:
        if get_state(self.session).paused:
            summary.paused = True
            self.events.emit(
                EventType.CONFIG_WARNING,
                f"system paused: skipping remaining orders from {order.symbol}",
                level=EventLevel.WARN,
                cycle_id=cycle_id,
            )
            return True
        return False

    def _process(
        self,
        order: NetOrder,
        state: _RunState,
        cycle_id: int | None,
        session_date: date,
        books: dict[str, Book],
        strategies: dict[str, Strategy],
        asset_by_symbol: dict[str, Asset],
        prices: dict[str, RefPrice],
        treasury: TreasuryBalances,
        treasury_nav: Decimal,
        hold_only: set[str],
        summary: ExecutionSummary,
    ) -> None:
        asset = asset_by_symbol.get(order.symbol)
        row = ExecutionOrder(
            local_id=self._next_local_id(),
            cycle_id=cycle_id,
            asset_id=asset.id if asset else 0,
            side=str(order.side),
            mode=str(self.adapter.mode),
            adapter=self.adapter.name,
            status=str(OrderStatus.PENDING),
            requested_quantity=order.quantity,
            requested_notional=q_money(order.notional),
            reference_price=order.price,
            contributions=[
                {"strategy": p.code, "quantity": str(p.quantity)} for p in order.participants
            ],
        )
        self.session.add(row)
        self.session.flush()
        summary.submitted += 1
        try:
            request = self._build_request(order, asset, treasury)
            assert asset is not None
            self._pre_trade(
                request,
                asset,
                prices.get(order.symbol),
                state.cash,
                state.positions.get(order.symbol, ZERO),
                treasury_nav,
                session_date,
                treasury.gas_eth,
                hold_only,
            )
            quote = self.adapter.quote(request)
            self._store_quote(row, quote, request)
            self.events.emit(
                EventType.QUOTE_RECEIVED,
                f"{row.local_id} {order.side} {order.symbol}: quote {quote.provider} price {quote.price:.6f} vs ref {order.price:.6f}",
                payload={
                    "order": row.local_id,
                    "provider": quote.provider,
                    "price": str(quote.price),
                    "reference": str(order.price),
                    "impact_bps": str(quote.price_impact_bps)
                    if quote.price_impact_bps is not None
                    else None,
                },
                cycle_id=cycle_id,
            )
            deviation = validators.validate_quote(
                quote,
                request,
                max_slippage_bps=self.settings.max_slippage_bps,
                max_price_impact_bps=self.settings.max_price_impact_bps,
                quote_staleness_sec=self.settings.quote_staleness_sec,
            )
            row.status = str(OrderStatus.VALIDATED)
            row.expected_price = quote.price
            row.quoted_quantity = quote.quantity(
                order.side, request.token_decimals, request.cash_decimals
            )
            row.quoted_notional = q_money(
                quote.notional(order.side, request.token_decimals, request.cash_decimals)
            )
            row.price_impact_bps = (
                quote.price_impact_bps if quote.price_impact_bps is not None else deviation
            )
            self.session.flush()
        except TradeRejected as rej:
            self._reject(row, rej, cycle_id, summary)
            return
        except Exception as e:  # quoting/provider errors are rejections, not fills
            self._reject(
                row, TradeRejected("QUOTE_ERROR", f"{type(e).__name__}: {e}"), cycle_id, summary
            )
            return

        def on_submitted(rec: TxRecord, row_id: int = row.id, local_id: str = row.local_id) -> None:
            self._store_tx(row_id, rec)
            self.session.commit()
            self.events.emit(
                EventType.EXECUTION_SUBMITTED,
                f"{local_id} broadcast {rec.kind} {rec.tx_hash}",
                payload={"order": local_id, "tx_hash": rec.tx_hash, "kind": str(rec.kind)},
                cycle_id=cycle_id,
            )
            self.session.commit()

        if self.live:
            row.status = str(OrderStatus.SUBMITTED)
            self.session.commit()
        result = self.adapter.execute(request, quote, on_submitted=on_submitted)
        self._finalize(
            row, order, request, result, books, strategies, asset, cycle_id, session_date, summary
        )
        if result.filled:
            qty, notional = D(result.executed_quantity), D(result.executed_notional)
            if order.side == Side.BUY:
                state.cash -= notional
                state.positions[order.symbol] = state.positions.get(order.symbol, ZERO) + qty
            else:
                state.cash += notional
                state.positions[order.symbol] = max(
                    state.positions.get(order.symbol, ZERO) - qty, ZERO
                )
        self.session.commit()

    # ------------------------------------------------------------------ helpers
    def _build_request(
        self, order: NetOrder, asset: Asset | None, treasury: TreasuryBalances
    ) -> TradeRequest:
        if asset is None:
            raise TradeRejected("UNKNOWN_TOKEN", f"{order.symbol} is not a registered asset")
        dep = next((d for d in asset.deployments if d.chain_id == self.settings.chain_id), None)
        if dep is None:
            raise TradeRejected(
                "UNKNOWN_TOKEN",
                f"{order.symbol} has no deployment on chain {self.settings.chain_id}",
            )
        cash_token = self.settings.cash_token_address or ("0x" + "0" * 40 if not self.live else "")
        if self.live and not self.settings.cash_token_address:
            raise TradeRejected("UNSUPPORTED_TOKEN", "CASH_TOKEN_ADDRESS is not configured")
        cash_decimals = self._cash_decimals()
        return TradeRequest(
            symbol=order.symbol,
            asset_id=asset.id,
            side=order.side,
            quantity=order.quantity,
            notional=q_money(order.notional),
            reference_price=order.price,
            token_address=dep.contract_address,
            token_decimals=dep.decimals or 18,
            cash_token_address=cash_token,
            cash_decimals=cash_decimals,
            taker=self.settings.executor_address or None,
        )

    def _cash_decimals(self) -> int:
        chain = getattr(self.adapter, "chain", None)
        if self.live and chain is not None and self.settings.cash_token_address:
            return int(chain.erc20_decimals(self.settings.cash_token_address))
        return 6 if self.settings.cash_token_symbol.upper() in ("USDG", "USDC", "USDT") else 18

    def _pre_trade(
        self,
        request: TradeRequest,
        asset: Asset,
        rp: RefPrice | None,
        cash: Decimal,
        position: Decimal,
        nav: Decimal,
        day: date,
        gas_eth: Decimal,
        hold_only: set[str],
    ) -> None:
        dep = next(d for d in asset.deployments if d.chain_id == self.settings.chain_id)
        validators.validate_token_addresses(
            request, dep.contract_address, request.cash_token_address
        )
        validators.validate_asset_status(
            symbol=asset.symbol,
            eligible=asset.eligible,
            hold_only=asset.symbol in hold_only,
            halted=asset.is_halted,
            side=request.side,
            verified_onchain=dep.verified_onchain,
            require_verified=self.live,
        )
        if self.live:
            validators.validate_reference_price(rp, asset.symbol, self.settings.price_staleness_sec)
        elif rp is None:
            raise TradeRejected("NO_PRICE", f"no reference price for {asset.symbol}")
        validators.validate_balance(request, treasury_cash=cash, treasury_position=position)
        validators.validate_gas(gas_eth, self.settings.min_gas_eth, self.live)
        validators.validate_order_size(
            request,
            treasury_nav=nav,
            max_order_pct=self.settings.max_order_pct_of_treasury,
            turnover_today=turnover_today(self.session, day),
            max_turnover_pct=self.settings.max_daily_turnover_pct,
        )

    def _store_quote(self, row: ExecutionOrder, quote: Quote, request: TradeRequest) -> None:
        q = ExecutionQuote(
            order_id=row.id,
            provider=quote.provider,
            sell_token=quote.sell_token or request.sell_token,
            buy_token=quote.buy_token or request.buy_token,
            sell_amount=Decimal(quote.sell_amount_raw),
            buy_amount=Decimal(quote.buy_amount_raw),
            min_buy_amount=Decimal(quote.min_buy_amount_raw)
            if quote.min_buy_amount_raw is not None
            else None,
            price=quote.price,
            price_impact_bps=quote.price_impact_bps,
            gas_estimate=quote.gas_estimate,
            gas_price_wei=Decimal(quote.gas_price_wei) if quote.gas_price_wei is not None else None,
            allowance_spender=quote.allowance_spender,
            allowance_required=quote.allowance_required,
            liquidity_available=quote.liquidity_available,
            route=quote.route,
            quoted_at=quote.quoted_at,
            expires_at=quote.expires_at,
        )
        self.session.add(q)
        row.status = str(OrderStatus.QUOTED)
        self.session.flush()

    def _store_tx(self, order_id: int, rec: TxRecord) -> BlockchainTransaction:
        existing = self.session.execute(
            select(BlockchainTransaction).where(BlockchainTransaction.tx_hash == rec.tx_hash)
        ).scalar_one_or_none()
        tx = existing or BlockchainTransaction(
            order_id=order_id,
            kind=str(rec.kind),
            chain_id=self.settings.chain_id,
            tx_hash=rec.tx_hash,
            from_address=rec.from_address,
            to_address=rec.to_address,
        )
        tx.status = str(rec.status)
        tx.nonce = rec.nonce
        tx.gas_limit = rec.gas_limit
        tx.gas_used = rec.gas_used
        tx.effective_gas_price_wei = (
            Decimal(rec.effective_gas_price_wei)
            if rec.effective_gas_price_wei is not None
            else None
        )
        tx.gas_cost_eth = rec.gas_cost_eth
        tx.gas_cost_usd = (
            q_money(rec.gas_cost_eth * self.eth_usd)
            if (rec.gas_cost_eth is not None and self.eth_usd)
            else None
        )
        tx.block_number = rec.block_number
        tx.error = rec.error
        if rec.status in (TxStatus.CONFIRMED, TxStatus.REVERTED):
            from datetime import UTC, datetime

            tx.confirmed_at = datetime.now(UTC)
        if existing is None:
            self.session.add(tx)
        self.session.flush()
        return tx

    def _reject(
        self,
        row: ExecutionOrder,
        rej: TradeRejected,
        cycle_id: int | None,
        summary: ExecutionSummary,
    ) -> None:
        row.status = str(OrderStatus.REJECTED)
        row.reject_reason = f"{rej.code}: {rej.message}"[:2000]
        self.session.flush()
        summary.rejected += 1
        self.events.emit(
            EventType.ORDER_REJECTED,
            f"{row.local_id} {row.side} rejected: {rej.code} — {rej.message}",
            level=EventLevel.WARN,
            payload={"order": row.local_id, "code": rej.code, "message": rej.message},
            cycle_id=cycle_id,
        )
        self.session.commit()

    def _finalize(
        self,
        row: ExecutionOrder,
        order: NetOrder,
        request: TradeRequest,
        result: ExecutionResult,
        books: dict[str, Book],
        strategies: dict[str, Strategy],
        asset: Asset,
        cycle_id: int | None,
        day: date,
        summary: ExecutionSummary,
    ) -> None:
        for rec in result.transactions:
            self._store_tx(row.id, rec)
        row.gas_used = result.gas_used
        row.gas_cost_eth = result.gas_cost_eth
        row.gas_cost_usd = (
            q_money(result.gas_cost_eth * self.eth_usd)
            if (result.gas_cost_eth is not None and self.eth_usd)
            else None
        )
        if not result.filled:
            row.status = str(OrderStatus.FAILED)
            row.reject_reason = (result.error or "execution failed")[:2000]
            summary.failed += 1
            self.session.flush()
            paused = record_failed_tx(
                self.session, self.events, self.settings.max_failed_txs_before_pause
            )
            self.events.emit(
                EventType.EXECUTION_FAILED,
                f"{row.local_id} {order.side} {order.symbol} FAILED: {row.reject_reason}"
                + (f" tx {result.tx_hash}" if result.tx_hash else ""),
                level=EventLevel.ERROR,
                payload={
                    "order": row.local_id,
                    "error": row.reject_reason,
                    "tx_hash": result.tx_hash,
                },
                cycle_id=cycle_id,
            )
            summary.paused = summary.paused or paused
            return
        qty, notional = D(result.executed_quantity), D(result.executed_notional)
        eff = D(result.effective_price)
        row.status = str(result.status)
        row.executed_quantity = qty
        row.executed_notional = q_money(notional)
        row.effective_price = eff
        row.slippage_bps = result.slippage_bps
        row.price_impact_bps = (
            result.price_impact_bps if result.price_impact_bps is not None else row.price_impact_bps
        )
        summary.filled += 1
        summary.gross_filled_notional += notional
        add_turnover(self.session, day, notional)
        if self.live:
            reset_failures(self.session)
        # treasury effect: simulated backend mutates; onchain is read back from the chain
        if self.simulated is not None:
            self.simulated.apply_swap(order.symbol, str(order.side), qty, notional, ZERO)
        # attribute to sleeves pro-rata at the effective price
        self._attribute(row, order, qty, eff, books, strategies, asset, cycle_id)
        self.session.flush()
        ev_type = EventType.EXECUTION_CONFIRMED if self.live else EventType.EXECUTION_DRY_RUN
        label = "CONFIRMED" if self.live else "DRY RUN filled"
        self.events.emit(
            ev_type,
            f"{row.local_id} {order.side} {qty:.6f} {order.symbol} {label} @ {eff:.6f} (slippage {D(result.slippage_bps or 0):.1f} bps)"
            + (f" tx {result.tx_hash} block {result.block_number}" if result.tx_hash else ""),
            payload={
                "order": row.local_id,
                "symbol": order.symbol,
                "side": str(order.side),
                "quantity": str(qty),
                "notional": str(q_money(notional)),
                "price": str(eff),
                "tx_hash": result.tx_hash,
                "block": result.block_number,
                "mode": str(self.adapter.mode),
            },
            cycle_id=cycle_id,
        )

    def _attribute(
        self,
        row: ExecutionOrder,
        order: NetOrder,
        qty: Decimal,
        price: Decimal,
        books: dict[str, Book],
        strategies: dict[str, Strategy],
        asset: Asset,
        cycle_id: int | None,
    ) -> None:
        kind = FillKind.ONCHAIN_EXECUTION if self.live else FillKind.DRY_RUN
        parts = split_pro_rata(qty, [(p.code, p.quantity) for p in order.participants])
        leftover = ZERO
        done: list[tuple[str, Decimal]] = []
        for p in parts:
            book = books.get(p.code)
            if book is None:
                leftover += p.quantity
                continue
            try:
                fill = book.apply_fill(order.symbol, order.side, p.quantity, price)
            except InsufficientCashError:
                affordable = (book.cash / price).quantize(Decimal("1e-18")) if price > 0 else ZERO
                if affordable > 0:
                    fill = book.apply_fill(order.symbol, order.side, affordable, price)
                    leftover += p.quantity - affordable
                else:
                    leftover += p.quantity
                    continue
            done.append((p.code, fill.quantity))
            self.repo.record_fill(
                strategy=strategies[p.code],
                asset=asset,
                fill=fill,
                kind=kind,
                cycle_id=cycle_id,
                execution_order_id=row.id,
            )
        if leftover > Decimal("1e-12"):
            # the treasury really holds these tokens; the sleeve with the most cash absorbs them
            richest = max(books.values(), key=lambda b: (b.cash, b.code))
            fill = richest.apply_fill(
                order.symbol, order.side, leftover, price, allow_overdraft=True
            )
            done.append((richest.code, fill.quantity))
            self.repo.record_fill(
                strategy=strategies[richest.code],
                asset=asset,
                fill=fill,
                kind=kind,
                cycle_id=cycle_id,
                execution_order_id=row.id,
            )
            self.events.emit(
                EventType.CONFIG_WARNING,
                f"{row.local_id}: {leftover} {order.symbol} attributed to {richest.code} beyond its pro-rata share (sleeve cash overdraft)",
                level=EventLevel.WARN,
                cycle_id=cycle_id,
            )
        row.contributions = [{"strategy": c, "quantity": str(q)} for c, q in done]


def trim_buys_to_sleeve_cash(
    buys: list[NetOrder], books: dict[str, Book], settings: Settings
) -> list[NetOrder]:
    """Scale each sleeve's buy participations so its planned spending fits its actual cash.

    Books already reflect completed sells. A sleeve whose sell was rejected (halt, no
    liquidity, reverted transaction) must not overspend on its buys.
    """
    pending: dict[str, Decimal] = {}
    for o in buys:
        for p in o.participants:
            pending[p.code] = pending.get(p.code, ZERO) + p.quantity * o.price
    factors: dict[str, Decimal] = {}
    for code, planned in pending.items():
        book = books.get(code)
        if book is None or planned <= 0:
            continue
        available = book.cash * (Decimal(1) - settings.min_trade_notional_pct / 100)
        if planned > available:
            factors[code] = max(available, ZERO) / planned
    if not factors:
        return buys
    out: list[NetOrder] = []
    for o in buys:
        parts = [
            Participation(
                p.code, (p.quantity * factors.get(p.code, Decimal(1))).quantize(Decimal("1e-18"))
            )
            for p in o.participants
        ]
        parts = [p for p in parts if p.quantity > Decimal("1e-12")]
        qty = sum((p.quantity for p in parts), ZERO)
        if qty <= Decimal("1e-12"):
            continue
        trimmed = NetOrder(o.symbol, o.side, qty, o.price, parts, list(o.notes))
        if qty < o.quantity:
            trimmed.notes.append("trimmed to sleeve cash after sells")
        out.append(trimmed)
    return out
