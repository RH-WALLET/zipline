"""Netting: sleeve targets -> internal crosses + net external orders, under treasury-relative risk limits.

Terminology (kept distinct everywhere in the system):
  SIGNAL             a strategy's desired target weight
  INTERNAL_CROSS     one sleeve sells to another inside the treasury; NO blockchain transaction
  ONCHAIN_EXECUTION  the residual net change that is actually traded on Robinhood Chain
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal

from zipline_engine.accounting.books import Book
from zipline_engine.core.money import ZERO, q_qty
from zipline_engine.db.enums import Side

QTY_EPS = Decimal("1e-12")


@dataclass(frozen=True)
class RiskLimits:
    max_single_asset_pct: Decimal
    max_order_pct_of_treasury: Decimal
    max_daily_turnover_pct: Decimal
    min_trade_notional_pct: Decimal
    cash_reserve_pct: Decimal
    sleeve_min_delta_pct: Decimal = Decimal("0.1")
    sleeve_cash_buffer_pct: Decimal = Decimal("0.5")


@dataclass
class SleeveDelta:
    code: str
    symbol: str
    quantity: Decimal  # signed raw tokens (+ buy, - sell)
    price: Decimal

    @property
    def notional(self) -> Decimal:
        return abs(self.quantity) * self.price

    @property
    def side(self) -> Side:
        return Side.BUY if self.quantity > 0 else Side.SELL


@dataclass
class CrossPlan:
    symbol: str
    buyer: str
    seller: str
    quantity: Decimal
    price: Decimal

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.price


@dataclass
class Participation:
    code: str
    quantity: Decimal


@dataclass
class NetOrder:
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal
    participants: list[Participation]
    notes: list[str] = field(default_factory=list)

    @property
    def notional(self) -> Decimal:
        return self.quantity * self.price

    def scale_to(self, new_qty: Decimal, note: str) -> None:
        new_qty = q_qty(max(new_qty, ZERO))
        if new_qty >= self.quantity:
            return
        self.participants = split_pro_rata(
            new_qty, [(p.code, p.quantity) for p in self.participants]
        )
        self.quantity = sum((p.quantity for p in self.participants), ZERO)
        self.notes.append(note)


@dataclass
class Dropped:
    code: str
    symbol: str
    quantity: Decimal
    reason: str


@dataclass
class NettingResult:
    sleeve_deltas: list[SleeveDelta]
    crosses: list[CrossPlan]
    net_orders: list[NetOrder]
    dropped: list[Dropped]
    risk_notes: list[str]
    aggregate_targets: dict[
        str, Decimal
    ]  # symbol -> treasury-level target notional (reference prices)
    sleeve_navs: dict[str, Decimal]

    @property
    def gross_internal_notional(self) -> Decimal:
        return sum((c.notional for c in self.crosses), ZERO)

    @property
    def gross_external_notional(self) -> Decimal:
        return sum((o.notional for o in self.net_orders), ZERO)


def split_pro_rata(total: Decimal, parts: list[tuple[str, Decimal]]) -> list[Participation]:
    """Split ``total`` proportionally to ``parts`` so the pieces sum EXACTLY to ``total`` (18 dp)."""
    total = q_qty(total)
    parts = sorted(((c, q) for c, q in parts if q > 0), key=lambda x: x[0])
    base = sum((q for _, q in parts), ZERO)
    if total <= 0 or base <= 0:
        return []
    out = [
        Participation(c, (total * q / base).quantize(Decimal("1e-18"), rounding=ROUND_DOWN))
        for c, q in parts
    ]
    remainder = total - sum((p.quantity for p in out), ZERO)
    if remainder != 0:
        largest = max(out, key=lambda p: (p.quantity, p.code))
        largest.quantity += remainder
    return [p for p in out if p.quantity > 0]


# --------------------------------------------------------------------------- step 1: sleeve deltas


def compute_sleeve_deltas(
    targets: dict[str, dict[str, Decimal]],
    books: dict[str, Book],
    prices: dict[str, Decimal],
    hold_only: set[str],
    limits: RiskLimits,
) -> tuple[list[SleeveDelta], list[Dropped], dict[str, Decimal]]:
    deltas: list[SleeveDelta] = []
    dropped: list[Dropped] = []
    navs: dict[str, Decimal] = {}
    for code in sorted(books):
        book = books[code]
        target = targets.get(code, {})
        nav = book.nav(prices)
        navs[code] = nav
        if nav <= 0:
            continue
        symbols = sorted(set(target) | set(book.held_symbols()))
        sleeve_deltas: list[SleeveDelta] = []
        for sym in symbols:
            px = prices.get(sym)
            pos = book.positions.get(sym)
            current = pos.quantity if pos is not None else ZERO
            if sym in hold_only and sym not in target:
                continue  # temporarily unavailable: carry the position, no trade
            if px is None or px <= 0:
                if sym in target and target[sym] > 0:
                    dropped.append(Dropped(code, sym, ZERO, "no_reference_price"))
                continue
            target_qty = q_qty(target.get(sym, ZERO) * nav / px)
            delta = q_qty(target_qty - current)
            if abs(delta) <= QTY_EPS:
                continue
            if abs(delta) * px < nav * limits.sleeve_min_delta_pct / 100:
                dropped.append(Dropped(code, sym, delta, "below_sleeve_min_delta"))
                continue
            sleeve_deltas.append(SleeveDelta(code, sym, delta, px))
        # cash feasibility: buys must be covered by cash + planned sells, keeping a small buffer
        buys = sum((d.notional for d in sleeve_deltas if d.quantity > 0), ZERO)
        sells = sum((d.notional for d in sleeve_deltas if d.quantity < 0), ZERO)
        buffer = nav * limits.sleeve_cash_buffer_pct / 100
        available = book.cash + sells - buffer
        if buys > available and buys > 0:
            factor = max(available, ZERO) / buys
            for d in sleeve_deltas:
                if d.quantity > 0:
                    d.quantity = q_qty(d.quantity * factor)
            sleeve_deltas = [d for d in sleeve_deltas if abs(d.quantity) > QTY_EPS]
        deltas.extend(sleeve_deltas)
    return deltas, dropped, navs


# --------------------------------------------------------------------------- step 2: crossing


def cross_internally(deltas: list[SleeveDelta]) -> tuple[list[CrossPlan], list[NetOrder]]:
    crosses: list[CrossPlan] = []
    net_orders: list[NetOrder] = []
    by_symbol: dict[str, list[SleeveDelta]] = {}
    for d in deltas:
        by_symbol.setdefault(d.symbol, []).append(d)
    for sym in sorted(by_symbol):
        group = by_symbol[sym]
        price = group[0].price
        buyers = sorted(((d.code, d.quantity) for d in group if d.quantity > 0), key=lambda x: x[0])
        sellers = sorted(
            ((d.code, -d.quantity) for d in group if d.quantity < 0), key=lambda x: x[0]
        )
        total_buy = sum((q for _, q in buyers), ZERO)
        total_sell = sum((q for _, q in sellers), ZERO)
        cross_qty = min(total_buy, total_sell)
        remaining_buy = dict(buyers)
        remaining_sell = dict(sellers)
        if cross_qty > QTY_EPS:
            buy_share = split_pro_rata(cross_qty, buyers)
            sell_share = split_pro_rata(cross_qty, sellers)
            # match buyer shares against seller shares (two-pointer, deterministic)
            i = j = 0
            b_left = [(p.code, p.quantity) for p in buy_share]
            s_left = [(p.code, p.quantity) for p in sell_share]
            while i < len(b_left) and j < len(s_left):
                bc, bq = b_left[i]
                sc, sq = s_left[j]
                q = min(bq, sq)
                if q > QTY_EPS:
                    crosses.append(CrossPlan(sym, bc, sc, q, price))
                    remaining_buy[bc] -= q
                    remaining_sell[sc] -= q
                b_left[i] = (bc, bq - q)
                s_left[j] = (sc, sq - q)
                if b_left[i][1] <= QTY_EPS:
                    i += 1
                if s_left[j][1] <= QTY_EPS:
                    j += 1
        net = total_buy - total_sell
        if net > QTY_EPS:
            parts = [(c, q) for c, q in remaining_buy.items() if q > QTY_EPS]
            net_orders.append(
                NetOrder(sym, Side.BUY, q_qty(net), price, split_pro_rata(q_qty(net), parts))
            )
        elif net < -QTY_EPS:
            parts = [(c, q) for c, q in remaining_sell.items() if q > QTY_EPS]
            net_orders.append(
                NetOrder(sym, Side.SELL, q_qty(-net), price, split_pro_rata(q_qty(-net), parts))
            )
    return crosses, net_orders


# --------------------------------------------------------------------------- step 3: risk limits


def apply_risk_limits(
    orders: list[NetOrder],
    *,
    treasury_nav: Decimal,
    treasury_cash: Decimal,
    treasury_positions: dict[str, Decimal],
    prices: dict[str, Decimal],
    limits: RiskLimits,
    turnover_today: Decimal = ZERO,
) -> tuple[list[NetOrder], list[str]]:
    notes: list[str] = []
    if treasury_nav <= 0:
        return [], ["treasury NAV is zero: no external orders"]
    out: list[NetOrder] = []
    for o in sorted(orders, key=lambda x: x.symbol):
        # max single asset exposure (buys only)
        if o.side == Side.BUY:
            current_val = treasury_positions.get(o.symbol, ZERO) * o.price
            max_val = treasury_nav * limits.max_single_asset_pct / 100
            room = max_val - current_val
            if o.notional > room:
                o.scale_to(
                    max(room, ZERO) / o.price,
                    f"MAX_SINGLE_ASSET_PCT {limits.max_single_asset_pct}% capped {o.symbol}",
                )
                notes.append(o.notes[-1])
        # max single order size
        max_order = treasury_nav * limits.max_order_pct_of_treasury / 100
        if o.notional > max_order:
            o.scale_to(
                max_order / o.price,
                f"MAX_ORDER_PCT_OF_TREASURY {limits.max_order_pct_of_treasury}% capped {o.symbol}",
            )
            notes.append(o.notes[-1])
        if o.quantity > QTY_EPS:
            out.append(o)
    # daily turnover
    budget = treasury_nav * limits.max_daily_turnover_pct / 100 - turnover_today
    gross = sum((o.notional for o in out), ZERO)
    if gross > budget:
        if budget <= 0:
            notes.append(
                f"MAX_DAILY_TURNOVER_PCT {limits.max_daily_turnover_pct}% exhausted: all external orders deferred"
            )
            return [], notes
        factor = budget / gross
        for o in out:
            o.scale_to(
                o.quantity * factor,
                f"MAX_DAILY_TURNOVER_PCT {limits.max_daily_turnover_pct}% scaled by {factor:.4f}",
            )
        notes.append(
            f"MAX_DAILY_TURNOVER_PCT {limits.max_daily_turnover_pct}% scaled orders by {factor:.4f}"
        )
    # cash reserve: buys cannot dip into the reserve
    reserve = treasury_nav * limits.cash_reserve_pct / 100
    buys = sum((o.notional for o in out if o.side == Side.BUY), ZERO)
    sells = sum((o.notional for o in out if o.side == Side.SELL), ZERO)
    spendable = treasury_cash + sells - reserve
    if buys > spendable and buys > 0:
        factor = max(spendable, ZERO) / buys
        for o in out:
            if o.side == Side.BUY:
                o.scale_to(
                    o.quantity * factor,
                    f"CASH_RESERVE_PCT {limits.cash_reserve_pct}% scaled buys by {factor:.4f}",
                )
        notes.append(
            f"CASH_RESERVE_PCT {limits.cash_reserve_pct}% protected: buys scaled by {factor:.4f}"
        )
    # minimum trade size (relative to treasury)
    min_notional = treasury_nav * limits.min_trade_notional_pct / 100
    final: list[NetOrder] = []
    for o in out:
        if o.quantity <= QTY_EPS:
            continue
        if o.notional < min_notional:
            notes.append(
                f"{o.symbol} {o.side} {o.notional:.4f} below MIN_TRADE_NOTIONAL_PCT: skipped"
            )
            continue
        final.append(o)
    return final, notes


# --------------------------------------------------------------------------- orchestration


def plan(
    targets: dict[str, dict[str, Decimal]],
    books: dict[str, Book],
    prices: dict[str, Decimal],
    *,
    hold_only: set[str],
    treasury_nav: Decimal,
    treasury_cash: Decimal,
    treasury_positions: dict[str, Decimal],
    limits: RiskLimits,
    turnover_today: Decimal = ZERO,
) -> NettingResult:
    deltas, dropped, navs = compute_sleeve_deltas(targets, books, prices, hold_only, limits)
    crosses, net_orders = cross_internally(deltas)
    net_orders, notes = apply_risk_limits(
        net_orders,
        treasury_nav=treasury_nav,
        treasury_cash=treasury_cash,
        treasury_positions=treasury_positions,
        prices=prices,
        limits=limits,
        turnover_today=turnover_today,
    )
    aggregate: dict[str, Decimal] = {}
    for code, tw in targets.items():
        nav = navs.get(code, ZERO)
        for sym, w in tw.items():
            aggregate[sym] = aggregate.get(sym, ZERO) + w * nav
    return NettingResult(
        deltas, crosses, net_orders, dropped, notes, dict(sorted(aggregate.items())), navs
    )
