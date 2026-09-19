# Product

<!-- impeccable:product-schema 1 -->

_Derived from the operator's written brief (2026-09-18). Items marked (inferred) were not stated verbatim and are assumptions._

## Platform

web

## Users
The operator of a single treasury wallet who runs deterministic quantitative strategies against Robinhood Stock Tokens on Robinhood Chain, and the public who inspects what the machine did: which rules fired, what was netted internally, what was actually traded onchain (with transaction hashes), and whether the books reconcile to the wallet. The operator uses the CLI and admin API; visitors read the web interface. (inferred) Visitors are quantitatively literate and skeptical of crypto marketing.

## Product Purpose
Run the open-source Quantopian engine lineage (zipline-reloaded) against real markets again: ten deterministic strategies produce target allocations, targets are netted into one treasury, the net change is executed as real Stock Token trades, and every step is recorded so any decision can be reproduced. Success means the live system is demonstrably truthful: real NAV, real fills, real hashes, books that reconcile.

## Positioning
One real wallet, one pool of capital, ten virtual strategy books, netted before anything touches the chain. No AI, no LLM, no generated decisions: same history + same configuration = same decision. The story is historical fact (Quantopian built Zipline; Robinhood acquired Quantopian; the engine survived as open source) and the appeal is the machinery, not lore.

## Operating Context
Daily cycle after the US equity close (16:20 ET) on NYSE sessions. Historical underlying-equity bars from a swappable provider (yfinance in development); live Stock Token pricing from Robinhood's public API (underlying bid/ask × ERC-8056 multiplier); execution through 0x RFQ on Robinhood Chain (chain 4663, ETH gas, USDG cash). Two non-live modes stamped DEMO MODE / LIVE TRADING DISABLED: a simulated database treasury, and read-only onchain monitoring with dry-run planning.

## Capabilities and Constraints
- Ten strategies: TREND, MOMENTUM, MEANREV, BREAKOUT, LOWVOL, REVERSAL, DUALMA, RISKON, PAIRS, ZEROIQ (PRNG control with persisted seed).
- Percent-based risk limits relative to treasury NAV; 10% cash reserve; emergency pause; auto-pause on repeated failures and reconciliation breaks.
- Long-only, no leverage, no margin, no shorting, no arbitrary ERC-20s. The project token is never held or traded by the treasury.
- Terminology to keep distinct: SIGNAL, INTERNAL_CROSS, ONCHAIN_EXECUTION; underlying price vs Stock Token value; contributions vs PnL.
- Dry-run records use obviously local identifiers (`dry-000042`), never hash-shaped ids.
- Undecided: production deploy target (README documents a single-VPS Docker Compose deploy).

## Brand Commitments
Name: ZIPLINE (uppercase). Voice: telemetry, not marketing. Headline copy is pinned: "ZIPLINE IS RUNNING AGAIN." / "The open-source Quantopian engine, reconnected to real markets on Robinhood Chain." / "Multiple deterministic quant strategies. One real treasury. Real Stock Token trades."

Visual commitment (operator decision, 2026-09-19, after rejecting the dark-terminal reading of the brief, a literal Read-the-Docs clone of zipline.io and a Quantopian red-navbar console): the interface is a **live tear sheet** — the pyfolio performance report of the Zipline ecosystem, typeset on warm paper (Source Serif 4 for words, Red Hat Mono for data, hairline rules), with the full `perf_stats` table (Annual return · Cumulative returns · Annual volatility · Sharpe · Calmar · Stability · Max drawdown · Omega · Sortino · Skew · Kurtosis · Tail ratio · Daily VaR · Alpha · Beta · Information ratio), cumulative-returns and underwater plots, rolling windows, and the ledgers as report sections; the Quantopian red survives only as the rule under the masthead and the rotated document stamp that names the mode. See DESIGN.md. Still forbidden from the original brief: neon, glassmorphism, gradients, floating coins, robots, AI orbs, avatars, anthropomorphized strategies, fake trades, fake hashes, fake numbers.

## Evidence on Hand
Real: Robinhood Stock Token API (194 tokens on chain 4663 as of 2026-09-18), zipline-reloaded 3.1.1 running the same strategy code in backtests, live dry-run cycle output, reconciliation events. Absent and never to be fabricated: live transaction hashes until LIVE_TRADING is enabled with a funded wallet; historical performance claims; testimonials.

## Product Principles
1. Truthful over flashy; telemetry over copy; mechanism over mystique.
2. Every number on screen is read from the system; nothing is hard-coded.
3. Distinguish what happened onchain from what happened inside the books, always.
4. Reproducibility is a feature: rules, parameters, versions and seeds are visible.
5. Safety defaults: live trading off, limits relative, pause on doubt.
