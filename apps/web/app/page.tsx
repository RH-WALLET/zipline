import Link from "next/link";
import { api, settle } from "@/lib/api";
import { explorerAddress, fmtAge, fmtEth, fmtInt, fmtMoney, fmtPct, fmtQty, fmtTime, fmtUntil, num, shortAddr, statusClass } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { CrossTable } from "@/components/CrossTable";
import { PerformanceCurve } from "@/components/Curves";
import { EventFeed } from "@/components/EventFeed";
import { ExecutionTable } from "@/components/ExecutionTable";
import { KV } from "@/components/KV";
import { Panel, Empty } from "@/components/Panel";
import { Money, Pct } from "@/components/Signed";
import { SignalTable } from "@/components/SignalTable";
import { RiskTable, StatsStrip } from "@/components/StatsStrip";
import { StrategyTable } from "@/components/StrategyTable";
import { Tabs } from "@/components/Tabs";
import { Unavailable } from "@/components/Unavailable";

export default async function Dashboard() {
  const [status, treasury, metrics, strategies, signals, crosses, executions, recon, events, cycles] = await Promise.all([
    settle(api.status()),
    settle(api.treasury()),
    settle(api.treasuryMetrics()),
    settle(api.strategies()),
    settle(api.signals(40)),
    settle(api.crosses(20)),
    settle(api.executions(25)),
    settle(api.reconciliation(1)),
    settle(api.events(80)),
    settle(api.cycles(5)),
  ]);
  if (!status || !treasury) {
    return (
      <div className="container">
        <div className="report-head">
          <h1>ZIPLINE treasury</h1>
        </div>
        <Unavailable />
      </div>
    );
  }

  const snap = treasury.snapshot;
  const lastRecon = recon?.[0] ?? null;
  const positionsCount = Object.keys(treasury.holdings).length;
  const explorer = status.chain.explorer_base_url;
  const wallet = treasury.wallet_address;
  const nav = num(snap?.nav) ?? 0;
  const gasSpentUsd = snap ? num(snap.cumulative_gas_usd) : null;
  const inception = cycles && cycles.length ? cycles[cycles.length - 1].started_at : null;
  const lastCycle = cycles?.[0] ?? null;

  const overview = (
    <div className="grid-2">
      <Panel title="Treasury" meta={snap ? `valued ${fmtAge(snap.taken_at)} · ${snap.mode}` : "no valuation yet"} flush>
        {snap ? (
          <div className="body">
            <KV
              ariaLabel="Zipline treasury"
              rows={[
                { label: "NAV", value: fmtMoney(snap.nav), big: true },
                { label: "Deployed", value: fmtMoney(snap.positions_value) },
                { label: `Cash (${treasury.cash_token.symbol})`, value: fmtMoney(snap.cash_balance) },
                { label: "Cash reserve target", value: <span className="muted">{fmtMoney(snap.reserved_cash)}</span> },
                {
                  label: "ETH gas balance",
                  value: (
                    <>
                      {fmtEth(snap.gas_balance_eth, 4)} <span className="muted">{snap.gas_balance_usd ? `≈ ${fmtMoney(snap.gas_balance_usd)}` : ""}</span>
                    </>
                  ),
                },
                { label: "Total return (TWR)", value: <Pct v={treasury.returns.total_return_pct} /> },
                { label: "Realized PnL", value: <Money v={snap.realized_pnl} sign /> },
                { label: "Unrealized PnL", value: <Money v={snap.unrealized_pnl} sign /> },
                {
                  label: "Gas spent",
                  value: (
                    <>
                      {fmtEth(snap.cumulative_gas_eth, 6)} <span className="muted">{gasSpentUsd !== null && gasSpentUsd > 0 ? `≈ ${fmtMoney(gasSpentUsd)}` : ""}</span>
                    </>
                  ),
                },
                { label: "Base capital", value: fmtMoney(snap.base_capital) },
                { label: "Contributions / withdrawals", value: `${fmtMoney(snap.contributions_total)} / ${fmtMoney(snap.withdrawals_total)}` },
                { label: "Positions", value: fmtInt(positionsCount) },
                {
                  label: "Executions",
                  value: (
                    <>
                      {fmtInt(status.counts.executions)} <span className="muted">({fmtInt(status.counts.real_transactions)} onchain)</span>
                    </>
                  ),
                },
                {
                  label: "Treasury wallet",
                  value: wallet ? (
                    <a href={explorerAddress(explorer, wallet)} target="_blank" rel="noopener noreferrer" title={wallet}>
                      {shortAddr(wallet)} ↗
                    </a>
                  ) : (
                    <span className="muted">not configured (simulated)</span>
                  ),
                },
              ]}
            />
          </div>
        ) : (
          <Empty>
            No treasury snapshot yet. Run <code>zl revalue</code> or wait for the worker.
          </Empty>
        )}
      </Panel>
      <div>
        <Panel title="System state" meta="read from the engine; nothing here is hard-coded" flush>
          <div className="body">
            <KV
              ariaLabel="System state"
              rows={[
                { label: "System", value: <Chip tone={status.mode.paused ? "red" : "green"}>{status.mode.paused ? "PAUSED" : "ONLINE"}</Chip> },
                { label: "Execution mode", value: <Chip tone={status.mode.live_trading ? "green" : "amber"}>{status.mode.execution_mode.replace("_", " ")}</Chip> },
                { label: "Treasury mode", value: status.mode.treasury_mode },
                { label: "Active strategies", value: `${status.counts.active_strategies + status.counts.watch_strategies} / ${status.counts.strategies}` },
                { label: "Last rebalance", value: fmtTime(status.system.last_cycle_at) },
                { label: "Next scheduled cycle", value: `${fmtTime(status.system.next_cycle_at)} (${fmtUntil(status.system.next_cycle_at)})` },
                { label: "Cycle time", value: `${status.system.cycle_time_et} ET · after the close · NYSE sessions` },
                { label: "Last completed session", value: status.system.last_completed_session },
                { label: "Last market data", value: fmtTime(status.system.last_market_data_at) },
                { label: "Last universe refresh", value: fmtTime(status.system.last_universe_refresh_at) },
                {
                  label: "Last reconciliation",
                  value: lastRecon ? (
                    <>
                      <Chip tone={statusClass(lastRecon.status)}>{lastRecon.status === "RECONCILIATION_OK" ? "OK" : "FAILED"}</Chip> <span className="muted">{fmtAge(lastRecon.run_at)}</span>
                    </>
                  ) : (
                    "never"
                  ),
                },
                { label: "Consecutive failed txs", value: String(status.system.consecutive_failed_txs) },
                { label: "Chain", value: `${status.chain.chain_id} · ${status.chain.rpc_configured ? "RPC configured" : "no RPC"}` },
              ]}
            />
          </div>
        </Panel>
        <Panel title="Live trading blockers" meta={status.live_trading_blockers.length ? `${status.live_trading_blockers.length} unmet requirements` : "all requirements met"} flush>
          <div className="body">
            {status.live_trading_blockers.length ? (
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                {status.live_trading_blockers.map((b) => (
                  <li key={b} style={{ margin: "3px 0" }}>
                    <code>{b}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="pos">none — live trading is armed</span>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );

  const holdings = (
    <Panel title="Aggregate holdings" meta="sum of the sleeve books in raw Stock Token units · valued at Robinhood mid × multiplier" flush>
      {positionsCount === 0 ? (
        <Empty>No positions. The treasury is in cash.</Empty>
      ) : (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <th>Asset</th>
                <th className="num">Quantity</th>
                <th className="num">Token price</th>
                <th className="num">Multiplier</th>
                <th className="num">Value</th>
                <th className="num">Weight</th>
                <th className="num">Unrealized</th>
                <th>Price source</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(treasury.holdings)
                .sort((a, b) => Number(b[1].market_value) - Number(a[1].market_value))
                .map(([sym, h]) => {
                  const tp = treasury.treasury_positions?.[sym];
                  return (
                    <tr key={sym}>
                      <td>
                        <span className="sym">{sym}</span>
                      </td>
                      <td className="num">{fmtQty(h.quantity)}</td>
                      <td className="num">{tp ? fmtMoney(tp.token_price) : "—"}</td>
                      <td className="num muted">{tp ? Number(tp.multiplier).toFixed(6) : "—"}</td>
                      <td className="num">{fmtMoney(h.market_value)}</td>
                      <td className="num muted">{nav > 0 ? fmtPct((Number(h.market_value) / nav) * 100, 1, false) : "—"}</td>
                      <td className="num">
                        <Money v={h.unrealized_pnl} sign />
                      </td>
                      <td className="muted small">{tp ? `${tp.price_source}${tp.stale === "true" ? " · stale" : ""}` : "—"}</td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );

  const reconciliation = (
    <div className="grid-2">
      <Panel title="Reconciliation" meta={lastRecon ? `${lastRecon.details.trigger ?? ""} · ${fmtAge(lastRecon.run_at)}` : "never"} flush foot={<Link href="/treasury#reconciliation">Reconciliation history →</Link>}>
        {lastRecon ? (
          <div className="body">
            <KV
              ariaLabel="Reconciliation"
              rows={[
                { label: "Status", value: <Chip tone={statusClass(lastRecon.status)}>{lastRecon.status}</Chip> },
                { label: "Lines compared", value: String(lastRecon.details.lines?.length ?? 0) },
                { label: "Max deviation", value: `${Number(lastRecon.max_break_bps).toFixed(2)} bps (tolerance ${lastRecon.tolerance_bps})` },
                { label: "Sleeve cash / treasury cash", value: `${fmtMoney(lastRecon.details.sleeve_cash)} / ${fmtMoney(lastRecon.details.treasury_cash)}` },
                { label: "Buffer (reserve) cash", value: `${fmtMoney(lastRecon.details.buffer_cash)} · target ${fmtMoney(lastRecon.details.reserve_target)}` },
                { label: "Position breaks", value: <span className={lastRecon.position_breaks.length ? "neg" : ""}>{lastRecon.position_breaks.length}</span> },
                { label: "Auto-pause triggered", value: lastRecon.triggered_pause ? <span className="neg">yes</span> : "no" },
              ]}
            />
          </div>
        ) : (
          <Empty>No reconciliation has run yet.</Empty>
        )}
      </Panel>
      <Panel title="Identity" flush>
        <div className="body" style={{ fontSize: 13 }}>
          <p style={{ margin: "0 0 8px" }}>
            After every execution and every hour the engine checks that Σ sleeve positions equal the treasury&apos;s positions per asset and that Σ sleeve cash ≤ treasury cash, within {lastRecon?.tolerance_bps ?? 10} bps of NAV per line. The cash the sleeves do not own is the reserve buffer.
          </p>
          <p className="muted" style={{ margin: 0 }}>A break is recorded as RECONCILIATION_FAILED and pauses live trading automatically.</p>
        </div>
      </Panel>
    </div>
  );

  return (
    <div className="container">
      <AutoRefresh seconds={60} />
      <div className="report-head">
        <div>
          <h1>
            ZIPLINE treasury <span className="sub">— ten deterministic strategies, one wallet</span>
          </h1>
          <div className="meta">
            {inception ? `Running since ${fmtTime(inception).slice(0, 10)}` : "No cycle yet"} · base capital {fmtMoney(snap?.base_capital)} · {metrics?.sessions ?? 0} completed sessions · benchmark {metrics?.benchmark ?? "SPY"} · zipline-reloaded {status.software.zipline_reloaded} · chain {status.chain.chain_id}
            {lastCycle ? (
              <>
                {" "}
                · last cycle <Link href={`/cycles/${lastCycle.id}`}>#{lastCycle.id}</Link> ({lastCycle.status.toLowerCase()})
              </>
            ) : null}
          </div>
        </div>
        <div className="actions">
          <Chip tone={status.mode.live_trading ? "green" : "amber"}>{status.mode.live_trading ? "LIVE" : "DEMO · DRY RUN"}</Chip>
          <Chip tone={status.mode.paused ? "red" : "green"}>{status.mode.paused ? "PAUSED" : "ONLINE"}</Chip>
        </div>
      </div>

      <StatsStrip metrics={metrics} totalReturnPct={treasury.returns.total_return_pct} />

      <Panel title="Cumulative performance" meta="time-weighted; contributions and withdrawals are flows, not returns">
        <PerformanceCurve metrics={metrics} label="Treasury" />
      </Panel>

      <Tabs
        tabs={[
          { id: "overview", label: "Overview", content: overview },
          { id: "strategies", label: "Strategies", count: strategies?.length ?? 0, content: <Panel title="Strategy sleeves" meta="allocation and performance of the ten virtual books · returns are time-weighted" flush foot={<Link href="/strategies">All strategies and their exact rules →</Link>}>{strategies ? <StrategyTable strategies={strategies} /> : <Empty>Strategies unavailable.</Empty>}</Panel> },
          { id: "holdings", label: "Holdings", count: positionsCount, content: holdings },
          { id: "risk", label: "Risk metrics", content: <Panel title="Risk metrics" meta="empyrical-reloaded · rolling windows over completed sessions" flush><div className="body">{<RiskTable metrics={metrics} />}</div></Panel> },
          { id: "signals", label: "Signals", count: signals?.length ?? 0, content: <Panel title="Recent signals" meta="SIGNAL — a strategy's target before netting; TARGETS rows carry the sleeve's full target vector" flush><SignalTable signals={(signals ?? []).slice(0, 25)} /></Panel> },
          { id: "crosses", label: "Internal crosses", count: crosses?.length ?? 0, content: <Panel title="Internal crosses" meta="INTERNAL_CROSS — netted between two sleeves inside the treasury; no blockchain transaction" flush><CrossTable crosses={crosses ?? []} /></Panel> },
          { id: "executions", label: "Executions", count: executions?.length ?? 0, content: <Panel title="Recent executions" meta="ONCHAIN_EXECUTION (or DRY RUN) — the net external change per asset after netting" flush foot={<Link href="/executions">Full execution ledger →</Link>}><ExecutionTable executions={(executions ?? []).slice(0, 15)} compact /></Panel> },
          { id: "reconciliation", label: "Reconciliation", content: reconciliation },
          { id: "logs", label: "Logs", content: <EventFeed initial={events ?? []} limit={200} height={520} /> },
        ]}
      />
      <p className="help">
        {status.counts.real_transactions === 0
          ? "No onchain transactions have been broadcast by this deployment. Rows marked DRY RUN are simulated fills with local identifiers; they are not blockchain activity."
          : `${status.counts.real_transactions} onchain transaction(s) recorded; each links to the Robinhood Chain explorer.`}
      </p>
    </div>
  );
}
