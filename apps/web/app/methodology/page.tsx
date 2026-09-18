import Link from "next/link";
import { api, settle } from "@/lib/api";

function Rule({ k, v }: { k: string; v: unknown }) {
  const text = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
  return (
    <tr>
      <th style={{ width: "1%", whiteSpace: "nowrap" }}>{k}</th>
      <td>{text}</td>
    </tr>
  );
}

export default async function MethodologyPage() {
  const [status, strategies] = await Promise.all([settle(api.status()), settle(api.strategies())]);
  const cfg = status?.config;
  const risk = (cfg?.risk ?? {}) as Record<string, string | number>;
  const details = await Promise.all((strategies ?? []).map((s) => settle(api.strategy(s.code))));

  return (
    <div className="container narrow">
      <div className="panel" style={{ padding: "8px 32px 24px" }}>
        <div className="prose">
      <h1>Methodology</h1>
      <p className="muted">What this is, where it comes from, and exactly how the numbers on the other pages are produced.</p>
      <div className="callout">
        <strong>Independent project.</strong> ZIPLINE is not operated, sponsored or endorsed by Robinhood Markets, Inc. or Quantopian. It uses the open-source Zipline lineage and Robinhood&apos;s public Stock Token infrastructure.
      </div>

      <h2>Provenance</h2>
      <h3>What Quantopian was</h3>
      <p>
        Quantopian (Boston, founded 2011) ran a browser-based platform where anyone could write, backtest and paper-trade quantitative equity strategies in Python against a shared institutional dataset, and later
        allocated outside capital to community algorithms. To power it, Quantopian wrote an open-source, event-driven backtesting engine and released it under the Apache 2.0 licence.
      </p>
      <h3>What Zipline is</h3>
      <p>
        That engine is Zipline: <code>initialize</code> / <code>handle_data</code> / <code>before_trading_start</code>, <code>schedule_function</code>, <code>order_target_percent</code>, <code>data.history</code>, the Pipeline API, data bundles, slippage and commission models, exchange calendars, and the companion libraries
        <code>empyrical</code>, <code>pyfolio</code> and <code>alphalens</code>. In late 2020 Quantopian wound down its community platform and its team joined Robinhood in an acquisition. Because the code was already open source, the engine survived the company: it is maintained today as <code>zipline-reloaded</code> (with <code>empyrical-reloaded</code>, <code>pyfolio-reloaded</code>,{" "}
        <code>alphalens-reloaded</code>) by Stefan Jansen and contributors.
      </p>
      <h3>What this project is</h3>
      <p>
        ZIPLINE is an independent project that runs <code>zipline-reloaded {status?.software.zipline_reloaded ?? ""}</code> and the surrounding ecosystem against real markets: ten deterministic strategies, one treasury wallet on Robinhood Chain, real Stock Token trades. It uses and depends on the open-source Zipline lineage; it does not claim to be Quantopian, to continue Quantopian officially, or to have recovered any private Quantopian or Robinhood software. The ten strategies are rule sets written for this project. They are not Quantopian algorithms, and no historical performance of any Quantopian community algorithm is implied.
      </p>
      <p>
        Robinhood Markets, Inc. and its affiliates do not operate, sponsor or endorse this project. Robinhood Stock Tokens, Robinhood Chain and the Robinhood Stock Token APIs are used as public infrastructure, in the same way any wallet or application can use them.
      </p>

      <h2>Architecture</h2>
      <h3>One wallet</h3>
      <p>
        There is exactly one treasury wallet ({status?.chain.wallet_address ?? "not yet configured in this deployment"}) holding the cash token ({cfg?.cash_token_symbol ?? "USDG"}) and Stock Tokens on Robinhood Chain (chain id {status?.chain.chain_id ?? 4663}, gas in ETH). Its onchain balances are the source of truth for how much capital exists. There is no fixed initial capital: the application reads the wallet.
      </p>
      <h3>Strategy sleeves</h3>
      <p>
        Every strategy has a virtual book — cash, positions in raw Stock Token units, cost basis, realized and unrealized PnL, a time-weighted return index and drawdown — but no wallet. The books are accounting sleeves inside the one treasury. Each sleeve receives a percentage of deployable capital (treasury NAV minus the cash reserve). Weights are stored in the database; the MVP uses equal weights and the allocation layer also implements manual, performance-weighted, volatility-adjusted and drawdown-adjusted policies for later use.
      </p>
      <h3>Netting and internal crosses</h3>
      <p>
        Each cycle, every strategy independently produces target weights for its own sleeve. Targets are converted to raw token deltas per sleeve. Where one sleeve wants to buy what another wants to sell, the overlap is crossed internally at the reference price (Robinhood mid × multiplier): both books change, nothing touches the chain, and the event is recorded as <code>INTERNAL_CROSS</code>. Only the residual net change per asset becomes an external order (<code>ONCHAIN_EXECUTION</code>, or <code>DRY RUN</code> when live trading is off). The three words are kept distinct everywhere: a <code>SIGNAL</code> is a wish, an internal cross is a transfer between books, an onchain execution is a transaction.
      </p>
      <h3>Real execution</h3>
      <p>
        Live orders go through the 0x Swap API (allowance-holder flow, RFQ liquidity on Robinhood Chain): quote → token address check → Stock Token status check → allowance (exact amount) → balance and gas checks → treasury-relative limits → slippage and price-impact checks → gas estimate → local signature → broadcast → receipt. The actual filled amounts are read from the ERC-20 Transfer logs of the confirmed receipt, never assumed from the quote. Fills are attributed back to the participating sleeves pro rata at the effective price. A reverted or dropped transaction is recorded as <code>FAILED</code> with its hash; a fill is never fabricated, and the system never falls back from live execution to simulated execution.
      </p>

      <h2>Data</h2>
      <h3>Historical bars</h3>
      <p>
        Strategies read daily OHLCV of the underlying US equities from a swappable <code>HistoricalMarketDataProvider</code> (this deployment: <code>{cfg?.history_provider ?? "yfinance"}</code>; Polygon, Alpaca, Twelve Data and Stooq are implemented behind the same interface). These are underlying-equity prices from a market-data vendor — they are not Robinhood Chain prices and are never presented as such. Bars are cached locally and refreshed incrementally; the trading calendar is NYSE via <code>exchange_calendars</code>. The same bars are ingested into a Zipline data bundle so any strategy can be backtested with the real simulator (<code>zl backtest</code>).
      </p>
      <h3>Live pricing and the multiplier</h3>
      <p>
        Live valuation uses Robinhood&apos;s public Stock Token API: the underlying bid/ask per share, halt flag and volume per token, plus each token&apos;s corporate-action multiplier. Stock Tokens implement the ERC-8056 scaled-amount extension: <code>balanceOf</code> is a raw amount that never rebases; <code>uiMultiplier</code> encodes splits and dividends. The value of a raw token is <code>underlying price × multiplier</code>. Books hold raw units, so a 4:1 split quadruples the multiplier, quarters the per-share price and leaves value and PnL unchanged. When an RPC is configured, the multiplier and contract are verified onchain and Chainlink&apos;s (already multiplier-adjusted) feeds can be read as a sanity check.
      </p>

      <h2>Accounting</h2>
      <h3>PnL</h3>
      <p>
        Positions use the average-cost method. Realized PnL is booked on sells (proceeds minus average cost); unrealized PnL is market value minus cost basis at the reference price. Sleeve and treasury returns are time-weighted: each valuation chains the period return <code>(NAV − flows) / previous NAV</code>, so capital added or removed never shows up as performance. Drawdown is measured on the time-weighted index from its peak.
      </p>
      <h3>Treasury, funding and gas</h3>
      <p>
        NAV = cash + Σ positions at reference prices. The dashboard separates base capital, additional contributions, withdrawals, trading PnL and gas. Incoming transfers of the cash token to the wallet are detected from Transfer logs and recorded as <code>FundingEvent</code>s (never as profit); new deployable capital is split across active sleeves by the allocation policy while the reserve share stays at treasury level. Withdrawals are recorded explicitly, reduce NAV, and are taken first from buffer cash, then pro rata from sleeve cash. Gas is paid in ETH, tracked per transaction in ETH and (when an ETH/USD price is available) USD, and reported separately from trading PnL.
      </p>
      <h3>Risk limits (percent of treasury NAV)</h3>
      <table>
        <tbody>
          <tr>
            <td><code>CASH_RESERVE_PCT</code></td>
            <td>{String(risk.cash_reserve_pct ?? "10")}% of NAV is never deployed to sleeves</td>
          </tr>
          <tr>
            <td><code>MAX_SINGLE_ASSET_PCT</code></td>
            <td>aggregate exposure to one asset ≤ {String(risk.max_single_asset_pct ?? "20")}%</td>
          </tr>
          <tr>
            <td><code>MAX_STRATEGY_ALLOCATION_PCT</code></td>
            <td>one sleeve ≤ {String(risk.max_strategy_allocation_pct ?? "20")}% of NAV</td>
          </tr>
          <tr>
            <td><code>MAX_ORDER_PCT_OF_TREASURY</code></td>
            <td>one external order ≤ {String(risk.max_order_pct_of_treasury ?? "10")}% (larger changes complete over several cycles)</td>
          </tr>
          <tr>
            <td><code>MAX_DAILY_TURNOVER_PCT</code></td>
            <td>gross external notional per day ≤ {String(risk.max_daily_turnover_pct ?? "50")}%</td>
          </tr>
          <tr>
            <td><code>MIN_TRADE_NOTIONAL_PCT</code></td>
            <td>orders below {String(risk.min_trade_notional_pct ?? "0.25")}% of NAV are skipped to avoid churn</td>
          </tr>
          <tr>
            <td><code>MAX_SLIPPAGE_BPS / MAX_PRICE_IMPACT_BPS</code></td>
            <td>
              quotes worse than {String(risk.max_slippage_bps ?? 100)} bps against the Robinhood reference, or with impact above {String(risk.max_price_impact_bps ?? 150)} bps, are rejected
            </td>
          </tr>
          <tr>
            <td><code>MAX_FAILED_TXS_BEFORE_PAUSE</code></td>
            <td>{String(risk.max_failed_txs_before_pause ?? 3)} consecutive failed executions pause the system</td>
          </tr>
          <tr>
            <td><code>WATCH / DISABLE drawdown</code></td>
            <td>
              a sleeve enters WATCH beyond −{String(risk.watch_drawdown_pct ?? "10")}% and is DISABLED beyond −{String(risk.disable_drawdown_pct ?? "25")}% (time-weighted, from peak); disabled sleeves liquidate to cash and keep their history
            </td>
          </tr>
        </tbody>
      </table>
      <p>
        Never: leverage, margin, shorting, borrowing, arbitrary ERC-20s. The project token is not held or traded by the treasury. Rejected outright: unknown or unsupported tokens, halted assets, stale prices or quotes, wrong network, insufficient balance or gas, oversized orders, turnover breaches, reconciliation errors.
      </p>
      <h3>Reconciliation</h3>
      <p>
        After every execution and every {" "}hour the system compares Σ sleeve positions with the treasury&apos;s positions per asset, and Σ sleeve cash with treasury cash, allowing {String(risk.reconciliation_tolerance_bps ?? 10)} bps of NAV per line for 18-decimal rounding and execution rounding. The remainder of treasury cash not owned by any sleeve is the reserve buffer. Any break is recorded as <code>RECONCILIATION_FAILED</code> and pauses live trading automatically. Reconciliation history is on the <Link href="/treasury#reconciliation">treasury page</Link>.
      </p>

      <h2 id="modes">Modes</h2>
      <p>
        <code>LIVE_TRADING=false</code> is the default and is labelled <strong>DEMO MODE / LIVE TRADING DISABLED</strong> everywhere. In that mode execution is a dry run: fills are simulated at Robinhood&apos;s underlying ask (buys) / bid (sells) × multiplier, carry local identifiers such as <code>dry-000042</code>, and never have a hash, gas or block. The treasury is either a simulated database balance or the real wallet read over RPC without trading. Live trading additionally requires a valid private key, the correct chain id, a working RPC, the configured cash token, a 0x API key, an initialized database, an unpaused system and a passing reconciliation. Blockers are listed on every deployment&apos;s <code>/status</code>.
      </p>

      <h2>Strategy rules</h2>
      <p>The rules below are rendered from each strategy&apos;s <code>describe_rules()</code> at request time, so they cannot drift from the code that runs. Version hashes cover the strategy source and its parameters.</p>
      {details.map((d) =>
        d ? (
          <div key={d.code}>
            <h3>
              <Link href={`/strategies/${d.code}`}>{d.code}</Link> <span className="wy-text-muted">— {d.name}</span>
            </h3>
            <p>{d.description}</p>
            <table>
              <tbody>
                {Object.entries(d.rules ?? {})
                  .filter(([k]) => k !== "parameters")
                  .map(([k, v]) => (
                    <Rule key={k} k={k} v={v} />
                  ))}
                <tr>
                  <td><code>parameters</code></td>
                  <td className="mono">{JSON.stringify(d.params ?? (d.rules?.parameters as unknown) ?? {})}</td>
                </tr>
                <tr>
                  <td><code>version / source</code></td>
                  <td className="mono">
                    {d.current_version_hash} / {d.source_hash}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : null,
      )}

      <h2>Software</h2>
      <table>
        <tbody>
          <tr>
            <td><code>engine</code></td>
            <td>zipline-engine {status?.software.engine ?? "—"} (Python 3.12, FastAPI, SQLAlchemy, PostgreSQL)</td>
          </tr>
          <tr>
            <td><code>zipline-reloaded</code></td>
            <td>{status?.software.zipline_reloaded ?? "—"} — Apache 2.0, github.com/stefan-jansen/zipline-reloaded</td>
          </tr>
          <tr>
            <td><code>calendar / metrics</code></td>
            <td>exchange-calendars (XNYS), empyrical-reloaded</td>
          </tr>
          <tr>
            <td><code>chain access</code></td>
            <td>web3.py, eth-account (local signing only)</td>
          </tr>
          <tr>
            <td><code>execution provider</code></td>
            <td>0x Swap API v2 (allowance-holder), RFQ liquidity on Robinhood Chain</td>
          </tr>
          <tr>
            <td><code>web</code></td>
            <td>Next.js, TypeScript, Tailwind</td>
          </tr>
          <tr>
            <td><code>licence</code></td>
            <td>Apache 2.0 for this project&apos;s code</td>
          </tr>
        </tbody>
      </table>
      <p className="muted">Nothing on this site is investment advice. The treasury can lose money; a control strategy that picks at random is part of the experiment precisely so the rule-based sleeves can be compared against chance.</p>
        </div>
      </div>
    </div>
  );
}
