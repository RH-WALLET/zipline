# ZIPLINE

[![ci](https://github.com/RH-WALLET/zipline/actions/workflows/ci.yml/badge.svg)](https://github.com/RH-WALLET/zipline/actions/workflows/ci.yml)

**ZIPLINE IS RUNNING AGAIN.**
The open-source Quantopian engine, reconnected to real markets on Robinhood Chain.

Multiple deterministic quant strategies. One real treasury. Real Stock Token trades.

---

## What this is

Quantopian built Zipline, an event-driven backtesting and live-trading engine, and released it as open source. Quantopian wound down in late 2020 and its team joined Robinhood in an acquisition. The engine survived because it was open source; it is maintained today as [`zipline-reloaded`](https://github.com/stefan-jansen/zipline-reloaded).

ZIPLINE runs that engine lineage against real markets again:

- **Ten deterministic strategies** (TREND, MOMENTUM, MEANREV, BREAKOUT, LOWVOL, REVERSAL, DUALMA, RISKON, PAIRS and a PRNG control, ZEROIQ) compute target allocations from historical underlying-equity bars. Same history + same configuration = same decision. No LLMs, no generated decisions, no "agents".
- **One treasury wallet** on Robinhood Chain (chain id 4663, gas in ETH, cash in USDG) holds the capital. Strategies are virtual accounting sleeves inside it; they never get wallets.
- **Netting**: sleeve targets are netted before anything touches the chain. Overlapping buys and sells are crossed internally (`INTERNAL_CROSS`, no transaction); only the residual per asset is executed (`ONCHAIN_EXECUTION`).
- **Real execution** through the 0x Swap API (RFQ liquidity on Robinhood Chain), with actual fills read from the confirmed receipt's Transfer logs — a quote is never assumed to be a fill.
- **Reconciliation** of Σ sleeve books against the real wallet after every execution and on a schedule; a break pauses live trading automatically.
- A web interface that presents the running system as a **live tear sheet** — the pyfolio performance report of the Zipline ecosystem, typeset and fed by the engine: the full `perf_stats` table (annual return, cumulative returns, volatility, Sharpe, Calmar, stability, max drawdown, Omega, Sortino, skew, kurtosis, tail ratio, daily VaR, alpha, beta, information ratio — all computed by empyrical from real valuations, `—` where history is too short), cumulative-returns and underwater plots against SPY, 1M/3M/6M/12M rolling windows, and the accounting, sleeves, holdings, signals, crosses, executions, reconciliation and system-log ledgers as sections of one report — for the treasury and for each strategy.
- A **terminal** (`/terminal`): the engine's own screen for watching — the live event tape over server-sent events (fills, crosses, quotes, risk checks, valuations, reconciliation), a Robinhood Stock Token quote board polled through the engine, treasury and books, UTC/ET clocks, NYSE session state and the countdown to the next cycle. Nothing on it is replayed or simulated; in demo mode it says so in the status bar.

This is an independent project. It is not operated, sponsored or endorsed by Robinhood Markets, Inc. or Quantopian. The ten strategies are rule sets written for this project; they are not Quantopian algorithms. Historical bars come from a market-data provider and are underlying-equity prices, not Robinhood Chain prices.

## Architecture

```
apps/web              Next.js 16 · TypeScript · Tailwind      live tear-sheet interface (pyfolio report, set live)
services/engine       Python 3.12 · FastAPI · SQLAlchemy       the engine
  zipline_engine/
    strategies/       ten Strategy implementations + registry (pure, deterministic)
    zipline_bridge/   Zipline data bundle from cached bars, algorithm wrapper, run_algorithm backtests
    marketdata/       HistoricalMarketDataProvider: yfinance (dev), stooq, polygon, alpaca, twelvedata + cache
    robinhood/        Stock Token API client, universe eligibility, live pricing (mid × multiplier)
    chain/            web3 RPC client (chain-id guard, ERC-20, ERC-8056 uiMultiplier, Chainlink), local signer
    accounting/       Book (sleeve) accounting, allocation policies, netting + internal crossing, status rules
    treasury/         simulated / onchain treasury backends, valuation, funding, withdrawals, gas oracle
    execution/        ExecutionAdapter: DryRunExecutionAdapter, ZeroXExecutionAdapter, validators, pipeline
    reconciliation/   Σ books vs wallet with tolerance; auto-pause
    scheduler/        daily cycle, valuation, reconciliation, funding scan, worker (APScheduler)
    api/              FastAPI routes, SSE stream, admin (bearer token)
  alembic/            migrations
  tests/              pytest (91 tests: determinism, accounting, netting, execution, reconciliation, API, e2e cycle)
docker-compose.yml    db (Postgres 16) · engine (API) · worker · web
```

One frontend, one Python backend, one Postgres, one worker. No Kubernetes.

### How strategy accounting works

Every strategy has a `Book`: virtual cash, positions in **raw Stock Token units**, average cost basis, realized PnL, a time-weighted return index and drawdown. Books are loaded from Postgres, mutated in memory during a cycle, and saved. A sleeve's NAV is its cash plus positions at the reference price. The sum of all books plus the treasury's reserve buffer is the treasury NAV; this identity is what reconciliation checks.

Returns are time-weighted: each valuation chains `(NAV − flows) / previous NAV`, so capital allocated to a sleeve (or a deposit to the treasury) is never counted as performance. Drawdown is measured on that index from its peak. Status is percentage-based: `WATCH` beyond `WATCH_DRAWDOWN_PCT`, `DISABLED` beyond `DISABLE_DRAWDOWN_PCT` (sticky; the operator re-enables). Disabled sleeves liquidate to cash and keep their history.

### Stock Token multiplier

Stock Tokens are ERC-20s with the ERC-8056 scaled-amount extension: `balanceOf` is a raw amount that never rebases; `uiMultiplier` encodes splits and dividends. Robinhood's price API returns the **underlying per-share** bid/ask, not multiplier-adjusted. Everything in ZIPLINE holds raw units and values them at `underlying price × multiplier`, so a 4:1 split (CRWD's multiplier is 4.0 today) changes neither value nor PnL. See `zipline_engine/core/multiplier.py`.

### Treasury architecture

`TreasuryService` reads balances from a backend — `OnchainTreasury` (RPC: cash token, every eligible Stock Token, ETH) or `SimulatedTreasury` (database rows, demo only) — values them with live prices, and snapshots NAV, cash, deployed value, reserve, gas, realized/unrealized PnL, cumulative gas, base capital, contributions, withdrawals and the TWR index. There is no fixed capital assumption: the wallet is the truth, whether it holds $50 or $50,000.

Deployable capital = NAV × (1 − `CASH_RESERVE_PCT`). Only deployable capital is distributed to sleeves; the reserve stays at treasury level. Incoming cash-token transfers are detected from Transfer logs and recorded as `FundingEvent`s; new deployable capital is split across active sleeves by the allocation policy (equal weight in the MVP; manual, performance-weighted, volatility-adjusted and drawdown-adjusted policies are implemented). Withdrawals are explicit (`zl treasury withdraw`), reduce NAV, and are never shown as losses.

### Netting

```
TREND     wants  +3% of treasury in NVDA
MOMENTUM  wants  +2%
MEANREV   wants  −1%
-----------------------------------------
internal cross     1%   MEANREV → TREND/MOMENTUM at the reference price (no transaction)
net external      +4%   one BUY order on 0x, attributed pro rata to TREND and MOMENTUM
```

`accounting/netting.py` computes sleeve deltas, crosses opposite sides per asset, and applies treasury-relative limits to the residual orders: `MAX_SINGLE_ASSET_PCT`, `MAX_ORDER_PCT_OF_TREASURY`, `MAX_DAILY_TURNOVER_PCT`, the cash reserve and `MIN_TRADE_NOTIONAL_PCT`. Sells execute before buys; buys are trimmed to what each sleeve can actually pay after any rejected sells.

### Execution architecture

`ExecutionAdapter` is the boundary: the engine hands it a `TradeRequest` and gets back a `Quote`, then an `ExecutionResult`. Two implementations ship:

- `DryRunExecutionAdapter` — DEMO MODE. Fills at Robinhood's underlying ask/bid × multiplier, ids like `dry-000042`, never a hash.
- `ZeroXExecutionAdapter` — LIVE. 0x Swap API v2 allowance-holder quote → exact-amount approve if needed → gas estimate → ETH check → local signature → broadcast → receipt → actual amounts from ERC-20 Transfer logs → slippage vs reference.

`execution/pipeline.py` runs every order through the validators (token addresses, Stock Token status and halt, reference-price freshness, balance, gas, order size, daily turnover, quote liquidity/slippage/impact/staleness), records `ExecutionOrder`, `ExecutionQuote` and `BlockchainTransaction` rows, mutates the simulated treasury in demo mode, attributes fills to sleeves at the effective price, and counts consecutive failures (auto-pause at `MAX_FAILED_TXS_BEFORE_PAUSE`). A failed transaction is recorded as `FAILED` with its hash; nothing is ever fabricated, and there is no silent fallback from live to dry-run.

## Local setup

Prerequisites: Docker (with Compose), or for native development Python 3.12, Node 22+, pnpm 11, Postgres.

```bash
git clone https://github.com/RH-WALLET/zipline.git && cd zipline
cp .env.example .env            # defaults are DEMO MODE with a simulated treasury
docker compose up --build       # db + engine (migrates, bootstraps) + worker + web
```

Open http://localhost:3000. The API is at http://localhost:8000 (OpenAPI docs at `/docs`).

The worker takes a valuation immediately and runs the daily cycle at `CYCLE_TIME_ET` on NYSE sessions. To run a cycle right now:

```bash
docker compose exec engine zl run-cycle
```

### Native development

```bash
# database
docker compose up -d db                                   # Postgres on localhost:5433

# engine
cd services/engine && python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://zipline:zipline@localhost:5433/zipline
alembic upgrade head && zl bootstrap
zl universe                     # live Stock Token universe → eligibility
zl load-history                 # historical bars into the cache
zl run-cycle                    # signals → netting → dry-run execution → reconciliation
zl reconcile · zl revalue · zl status
zl serve                        # API on :8000
zl worker                       # scheduler (separate terminal)
zl backtest DUALMA --start 2025-06-02 --end 2026-09-17    # Zipline simulator on the cached bundle

# web
cd apps/web && pnpm install && ENGINE_URL=http://127.0.0.1:8000 pnpm dev
```

### Tests, lint, types, build

```bash
cd services/engine && pytest && ruff check . && ruff format --check . && mypy zipline_engine
cd apps/web && pnpm test && pnpm lint && pnpm typecheck && pnpm build
cd apps/web && pnpm e2e         # Playwright smoke tests against a running stack
```

Backend tests use `TEST_DATABASE_URL` (default `postgresql+psycopg://zipline:zipline@localhost:5433/zipline_test`; create it with `docker exec zipline-db-1 psql -U zipline -d zipline -c "CREATE DATABASE zipline_test"`). Demo tests never broadcast a transaction; the live adapter is tested against a fake chain.

## Environment variables

Everything is in [`.env.example`](.env.example). The ones that matter:

| Variable | Meaning |
|---|---|
| `LIVE_TRADING` | `false` (default) = DEMO MODE, dry-run only. `true` = real onchain trades. |
| `TREASURY_MODE` | `simulated` (database treasury, demo) or `onchain` (read the real wallet over RPC). |
| `DEMO_INITIAL_CASH` | seed cash for the simulated treasury only. |
| `DATABASE_URL` | Postgres DSN. |
| `CHAIN_ID` | must be `4663` (Robinhood Chain) for live trading. |
| `RH_RPC_URL` | Robinhood Chain RPC. The public `https://rpc.mainnet.chain.robinhood.com` is rate-limited; use a dedicated endpoint for live. |
| `EXPLORER_BASE_URL` | `https://robinhoodchain.blockscout.com` |
| `EXECUTOR_ADDRESS` / `EXECUTOR_PRIVATE_KEY` | the treasury wallet. Dedicated wallet only. The key never leaves the engine process and is redacted from logs and errors. |
| `CASH_TOKEN_ADDRESS` / `CASH_TOKEN_SYMBOL` | settlement asset; USDG `0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168` by default. |
| `RH_STOCK_TOKEN_API_URL` | `https://api.robinhood.com/rhj` (public, no key). |
| `ASSET_ALLOWLIST` | symbols allowed into the universe (applied on top of what Robinhood lists). |
| `PAIRS_CANDIDATES` | candidate pairs for PAIRS, e.g. `SPY:QQQ,AAPL:MSFT`. |
| `ZEROX_API_URL` / `ZEROX_API_KEY` | 0x Swap API v2. |
| `HISTORY_PROVIDER` | `yfinance` (dev default, unofficial) · `stooq` · `polygon` · `alpaca` · `twelvedata` (+ their keys). |
| `CYCLE_TIME_ET` | daily cycle time, Eastern, after the close (default `16:20`). |
| `CASH_RESERVE_PCT`, `MAX_SINGLE_ASSET_PCT`, `MAX_STRATEGY_ALLOCATION_PCT`, `MAX_ORDER_PCT_OF_TREASURY`, `MAX_DAILY_TURNOVER_PCT`, `MIN_TRADE_NOTIONAL_PCT`, `MAX_SLIPPAGE_BPS`, `MAX_PRICE_IMPACT_BPS`, `MAX_FAILED_TXS_BEFORE_PAUSE`, `PRICE_STALENESS_SEC`, `QUOTE_STALENESS_SEC`, `MIN_GAS_ETH`, `RECONCILIATION_TOLERANCE_BPS`, `WATCH_DRAWDOWN_PCT`, `DISABLE_DRAWDOWN_PCT` | risk controls, all relative to treasury NAV. |
| `ADMIN_TOKEN` | bearer token for `POST /admin/*`. Empty disables admin endpoints. |
| `ETH_USD_PRICE_SOURCE` | `coinbase` (public spot), `chainlink` (+ `CHAINLINK_ETH_USD_FEED`) or `none`; only for reporting gas in USD. |
| `PROJECT_TOKEN_ADDRESS` | optional; if set, the address is shown with a note that the treasury never holds or trades it. |
| `ENGINE_URL` | how the web app reaches the engine (server-side). |

## Demo mode

`LIVE_TRADING=false` is the default. The interface shows **DEMO MODE** and **LIVE TRADING DISABLED** in the status bar and on every page that carries treasury or execution data. Two sub-modes:

- `TREASURY_MODE=simulated`: a database-backed treasury seeded with `DEMO_INITIAL_CASH`; strategies run on real history, valuations use real Robinhood prices, execution is a dry run at bid/ask, books and the simulated wallet reconcile. Deposits: `zl demo deposit 1000` or `POST /admin/demo/deposit`.
- `TREASURY_MODE=onchain` with `LIVE_TRADING=false`: the real wallet's balances are read over RPC and shown; cycles plan and dry-run orders but never broadcast.

Dry-run records carry local ids (`dry-000042`), have no hash, gas or block, and `/transactions` stays empty. They cannot be mistaken for chain activity.

## Live mode

Live trading is refused unless **all** of the following hold; `/status` lists every blocker:

1. `LIVE_TRADING=true` and `TREASURY_MODE=onchain`
2. `RH_RPC_URL` reachable **and** reporting chain id 4663
3. `EXECUTOR_PRIVATE_KEY` valid and matching `EXECUTOR_ADDRESS`
4. `CASH_TOKEN_ADDRESS` set (USDG) and `ZEROX_API_KEY` set
5. database migrated and bootstrapped (`zl bootstrap`)
6. system not paused
7. last reconciliation `RECONCILIATION_OK`

Going live:

```bash
# 1. dedicated wallet: put its address in EXECUTOR_ADDRESS and its key in EXECUTOR_PRIVATE_KEY (only in .env, never in git)
# 2. fund it on Robinhood Chain: USDG for trading capital, ETH for gas (keep > MIN_GAS_ETH)
# 3. start read-only first
TREASURY_MODE=onchain LIVE_TRADING=false docker compose up -d
docker compose exec engine zl status         # watch balances, universe, blockers
docker compose exec engine zl run-cycle      # dry-run plan against the real wallet
# 4. when the plan looks right
LIVE_TRADING=true docker compose up -d engine worker
```

The opening cash balance at bootstrap is recorded as `BASE_CAPITAL`; later transfers to the wallet are detected as `CONTRIBUTION`s (proceeds of the treasury's own swaps are excluded). Gas is tracked per transaction.

### Emergency pause

```bash
docker compose exec engine zl pause --reason "manual"     # or POST /admin/pause with the bearer token
docker compose exec engine zl resume
```

The system pauses itself on `MAX_FAILED_TXS_BEFORE_PAUSE` consecutive execution failures and on any reconciliation break. While paused no cycle runs and no order is sent.

### Robinhood Chain, Stock Token API, 0x, market data

- **Robinhood Chain**: chain id 4663, ETH gas, Blockscout explorer. The engine verifies `eth_chainId` on every connection and refuses any other network.
- **Stock Token APIs**: `GET /rhj/assets` (symbols, per-chain deployments, current and pending multiplier, trading capabilities, status), `GET /rhj/prices/{symbol}` (underlying bid/ask, halt flag, volume), `GET /rhj/corporate-actions`. No key. Eligibility requires: listed, deployed on 4663 (contract verified over RPC when available), `ASSET_STATUS_ACTIVE`, tradable, priced with a sane spread, not halted, non-zero reported volume, and — when 0x is configured — a live route probe within `MAX_PRICE_IMPACT_BPS`. Temporarily unavailable assets (halted, unpriced, missing from a response) become *hold-only*: positions are carried, nothing is traded. Inactive or de-listed assets are liquidated when a route exists.
- **0x**: Swap API v2 allowance-holder flow with RFQ liquidity on Robinhood Chain. Get a key at 0x.org; put it in `ZEROX_API_KEY`. Approvals are for the exact sell amount, never unlimited.
- **Historical data**: `HISTORY_PROVIDER` selects the provider; keyed providers fail at startup with the missing variable named. Bars are cached in Postgres and refreshed incrementally; `zl load-history --force` re-downloads a symbol (do this after a split changes the adjusted series).

## Operating the strategies

- **Change allocation weights**: update `strategy_allocations` (set the current row `active=false`, insert a new row with `weight_pct`); the `MANUAL` policy renormalizes over active sleeves. New deposits and reserve rebalancing follow the new weights immediately; existing sleeve NAVs drift with performance rather than being forcibly rebalanced.
- **Change strategy parameters**: insert a `strategy_versions` row with new `params`; the next cycle uses the latest version's params and records the new version hash on every signal.
- **Enable / disable**: `zl strategy disable TREND` / `zl strategy enable TREND` or `POST /admin/strategy/TREND/{enable,disable}`.
- **Add a strategy**: subclass `zipline_engine.strategies.base.Strategy`, implement `generate_signals`, `calculate_target_weights`, `describe_rules` (and `min_history`), register it in `strategies/registry.py`, run `zl bootstrap`. Keep it long-only and deterministic; the base class rejects negative weights, leverage and out-of-universe symbols. Historical Quantopian algorithms with compatible licences can be ported the same way — do not present them as anything but ports.
- **Add an execution adapter**: implement `ExecutionAdapter.quote` / `execute` in `zipline_engine/execution/`, returning real amounts from the receipt, and select it in `runtime.build_adapter`.
- **Add a historical-data provider**: subclass `HistoricalMarketDataProvider.fetch_daily_bars(symbol, start, end)` in `marketdata/providers.py` and add it to `build_provider`. Strategy code never changes.

## API

`GET /health` `GET /status` `GET /treasury` `GET /treasury/history` `GET /treasury/funding` `GET /treasury/metrics` `GET /assets` `GET /quotes` (live Robinhood bid/ask, 20 s server cache, display only) `GET /strategies` `GET /strategies/{code}` `GET /strategies/{code}/{positions,history,metrics,signals,fills,crosses,executions}` `GET /signals` `GET /executions` `GET /transactions` `GET /crosses` `GET /fills` `GET /reconciliation` `GET /events` `GET /events/stream` (SSE) `GET /cycles` `GET /cycles/{id}`

Admin (`Authorization: Bearer $ADMIN_TOKEN`): `POST /admin/pause` `POST /admin/resume` `POST /admin/run-cycle` `POST /admin/reconcile` `POST /admin/revalue` `POST /admin/strategy/{code}/enable` `POST /admin/strategy/{code}/disable` `POST /admin/demo/deposit` `POST /admin/withdraw`.

## Deploying

### Fly.io (the reference deployment)

The public instance runs on Fly.io: web at https://zipline-rh-web.fly.dev, engine API at https://zipline-rh-engine.fly.dev (`/docs`). Config lives in `services/engine/fly.toml` (two process groups: `api` and `worker`, release command runs migrations + bootstrap) and `apps/web/fly.toml`. To reproduce under your own account:

```bash
fly apps create <engine-app> && fly apps create <web-app>
fly postgres create --name <db-app> --region iad --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 1
fly postgres attach <db-app> --app <engine-app>                 # sets DATABASE_URL (postgres://… is normalized to psycopg)
fly secrets set ADMIN_TOKEN=$(openssl rand -hex 32) --app <engine-app>
# edit the app names in both fly.toml files, then:
fly deploy --config services/engine/fly.toml --remote-only
fly ips allocate-v4 --shared --app <engine-app> && fly ips allocate-v6 --app <engine-app>
fly scale count api=1 worker=1 --app <engine-app>
fly deploy --config apps/web/fly.toml --remote-only              # ENGINE_URL points at the engine's fly.dev URL
fly ips allocate-v4 --shared --app <web-app> && fly ips allocate-v6 --app <web-app>
fly ssh console --app <engine-app> -C "zl run-cycle"           # first cycle now instead of waiting for 16:20 ET
```

Going live on Fly: `fly secrets set RH_RPC_URL=… EXECUTOR_ADDRESS=… EXECUTOR_PRIVATE_KEY=… ZEROX_API_KEY=… --app <engine-app>`, set `TREASURY_MODE=onchain` (and later `LIVE_TRADING=true`) in `services/engine/fly.toml` `[env]`, redeploy. Redeploys re-run migrations and the idempotent bootstrap.

### Any VPS

A single VPS is enough:

```bash
# on the server
git clone https://github.com/RH-WALLET/zipline.git && cd zipline && cp .env.example .env && $EDITOR .env    # set ADMIN_TOKEN, RPC, wallet, 0x key
docker compose up -d --build
```

Put Caddy or nginx in front of `web:3000` (and, if you want the raw API public, `engine:8000`) with TLS. Keep Postgres and the engine off the public interface; back up the `pgdata` volume — it holds every signal, fill, quote and transaction needed to reproduce a decision. `enginedata` holds the Zipline bundle and history cache and can be rebuilt.

## Security

- `EXECUTOR_PRIVATE_KEY`, API keys and `ADMIN_TOKEN` are `SecretStr`s: never in `repr`, never returned by any endpoint, redacted from every log line and persisted error message.
- Admin endpoints require a bearer token and are not proxied by the web app.
- Use a dedicated treasury wallet. Fund it with what you are prepared to trade.
- Never commit `.env`.

## Licence

Apache 2.0 for this project. `zipline-reloaded`, `empyrical-reloaded` and `exchange-calendars` are Apache 2.0. Not investment advice; the treasury can lose money.
