# ZIPLINE — notes for future sessions

Read `README.md` for the system, `PRODUCT.md` for the brief's product truth, `DESIGN.md` for the web interface's visual rules.

## Non-negotiables from the brief
- No AI/LLM anywhere in the product: no generated decisions, commentary, personalities or "agents". Strategies are deterministic rule sets; ZEROIQ is a persisted-seed PRNG control.
- Never fabricate: no fake trades, hashes, numbers or performance. Dry-run ids look like `dry-000042`; only real broadcasts create `BlockchainTransaction` rows and explorer links.
- Keep `SIGNAL` / `INTERNAL_CROSS` / `ONCHAIN_EXECUTION` distinct everywhere. Contributions are never PnL. Historical bars are underlying-equity data, never described as chain data.
- Live trading stays off by default and never silently falls back to simulation. Risk limits are percentages of treasury NAV, never fixed dollars.
- Visual world (operator decision after three rejected directions): a **live tear sheet** — pyfolio's performance report typeset on paper: Source Serif 4 + Red Hat Mono, hairlines, `table.stats` with the full perf_stats set, cumulative-returns/underwater plots, ledgers as report sections, one red rule under the masthead and a red document stamp for the mode (see DESIGN.md). No dashboard boxes, tabs or panels. The stamp reads DEMO MODE / live trading disabled · dry run on every page while live trading is off. Performance statistics come from `/treasury/metrics` and `/strategies/{code}/metrics` (empyrical); null means not enough history and renders as "—", never an estimate. Data tables must fit 1116px without a horizontal scrollbar: stack paired facts with `.sub` instead of adding columns.

## Working on the engine
- `services/engine`, Python 3.12 venv at `.venv`; `pytest`, `ruff check .`, `ruff format .`, `mypy zipline_engine` must stay clean.
- DB tests need Postgres at `localhost:5433` (`docker compose up -d db`) and a `zipline_test` database.
- All accounting is `Decimal`; raw Stock Token units in books; value = underlying price × ERC-8056 multiplier.
- Schema changes: edit `db/models.py`, then `alembic revision --autogenerate`.

## Working on the web app
- `apps/web`, pnpm; `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm build`; `pnpm e2e` needs the stack running.
- Route groups: `app/(report)/*` is the paper tear sheet (masthead + colophon layout); `app/terminal` is the dark full-screen terminal with its own layout and `terminal.css`. The root layout carries only fonts and the document. `(report)/[...missing]` routes unknown paths to the report's not-found page.
- The terminal shows only real activity: SSE events, `GET /quotes` (Robinhood bid/ask through the engine, 20 s server cache), accounting endpoints. No replays, no simulated ticks — see DESIGN.md.
- Server components fetch the engine with `cache: "no-store"`; client components go through `/api/engine/*` (GET only) and `/api/stream` (SSE).
- Next 16: `params` are Promises; read `node_modules/next/dist/docs` before assuming an API.
