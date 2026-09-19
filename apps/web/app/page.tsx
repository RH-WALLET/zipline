import Link from "next/link";
import { api, settle } from "@/lib/api";
import { explorerAddress, fmtAge, fmtEth, fmtInt, fmtMoney, fmtPct, fmtQty, fmtTime, fmtUntil, num, shortAddr, statusClass } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { CrossTable } from "@/components/CrossTable";
import { EventFeed } from "@/components/EventFeed";
import { ExecutionTable } from "@/components/ExecutionTable";
import { KV } from "@/components/KV";
import { PerfStats, RollingTable } from "@/components/PerfStats";
import { ReportTitle } from "@/components/ReportTitle";
import { Contents, Empty, Section } from "@/components/Section";
import { Money, Pct } from "@/components/Signed";
import { SignalTable } from "@/components/SignalTable";
import { StrategyTable } from "@/components/StrategyTable";
import { CumulativeReturns, DailyReturns, MonthlyReturns, Underwater } from "@/components/TearPlots";
import { Unavailable } from "@/components/Unavailable";

export default async function TreasuryReport() {
  const [status, treasury, metrics, strategies, signals, crosses, executions, recon, events, cycles] = await Promise.all([
    settle(api.status()),
    settle(api.treasury()),
    settle(api.treasuryMetrics()),
    settle(api.strategies()),
    settle(api.signals(30)),
    settle(api.crosses(15)),
    settle(api.executions(15)),
    settle(api.reconciliation(1)),
    settle(api.events(60)),
    settle(api.cycles(5)),
  ]);
  if (!status || !treasury) {
    return (
      <div className="page">
        <ReportTitle kicker="ZIPLINE · treasury report" title="Treasury" status={status} />
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

  return (
    <div className="page">
      <AutoRefresh seconds={60} />
      <ReportTitle
        kicker={`ZIPLINE · treasury report · as of ${fmtTime(snap?.taken_at ?? new Date().toISOString())}`}
        title="Treasury"
        sub="ten deterministic strategies, one wallet"
        lede={
          <>
            <strong>ZIPLINE is running again.</strong> The open-source Quantopian engine, reconnected to real markets on Robinhood Chain. Multiple deterministic quant strategies, one real treasury, real Stock Token trades — netted, executed, reconciled, and reported here as it happens.
          </>
        }
        facts={[
          <>
            NAV <b>{fmtMoney(snap?.nav)}</b>
          </>,
          <>
            base capital <b>{fmtMoney(snap?.base_capital)}</b>
          </>,
          <>
            running since <b>{inception ? fmtTime(inception).slice(0, 10) : "—"}</b>
          </>,
          <>
            sessions <b>{metrics?.sessions ?? 0}</b>
          </>,
          <>
            benchmark <b>{metrics?.benchmark ?? "SPY"}</b>
          </>,
          <>
            engine <b>zipline-reloaded {status.software.zipline_reloaded}</b>
          </>,
          <>
            chain <b>{status.chain.chain_id}</b>
          </>,
          lastCycle ? (
            <>
              last cycle{" "}
              <b>
                <Link href={`/cycles/${lastCycle.id}`}>#{lastCycle.id}</Link> {lastCycle.status.toLowerCase()}
              </b>
            </>
          ) : (
            <>no cycle yet</>
          ),
        ]}
        status={status}
      />
      <Contents
        items={[
          ["performance", "Performance"],
          ["accounting", "Accounting"],
          ["sleeves", "Strategy sleeves"],
          ["holdings", "Holdings"],
          ["signals", "Signals"],
          ["crosses", "Internal crosses"],
          ["executions", "Executions"],
          ["reconciliation", "Reconciliation"],
          ["log", "Log"],
        ]}
      />

      <Section id="performance" title="Performance" note={`time-weighted · benchmark ${metrics?.benchmark ?? "SPY"} · statistics by empyrical-reloaded`}>
        <div className="cols">
          <PerfStats metrics={metrics} heroLabel="Total return" heroPct={treasury.returns.total_return_pct} />
          <div>
            <CumulativeReturns metrics={metrics} label="Treasury" />
            <Underwater metrics={metrics} />
            <DailyReturns metrics={metrics} />
            <MonthlyReturns metrics={metrics} />
          </div>
        </div>
        <h3>Rolling windows</h3>
        <RollingTable metrics={metrics} />
      </Section>

      <Section id="accounting" title="Accounting" note={snap ? `${snap.mode} treasury · valued ${fmtAge(snap.taken_at)}` : "no valuation yet"}>
        <div className="cols even">
          <div>
            <h3>Treasury</h3>
            {snap ? (
              <KV
                ariaLabel="Zipline treasury"
                rows={[
                  { label: "Net asset value", value: fmtMoney(snap.nav), big: true },
                  { label: "Deployed in Stock Tokens", value: fmtMoney(snap.positions_value) },
                  { label: `Cash (${treasury.cash_token.symbol})`, value: fmtMoney(snap.cash_balance) },
                  { label: "Cash reserve target", value: fmtMoney(snap.reserved_cash) },
                  {
                    label: "ETH for gas",
                    value: (
                      <>
                        {fmtEth(snap.gas_balance_eth, 4)} <span className="muted">{snap.gas_balance_usd ? `≈ ${fmtMoney(snap.gas_balance_usd)}` : ""}</span>
                      </>
                    ),
                  },
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
                  { label: "Time-weighted return", value: <Pct v={treasury.returns.total_return_pct} /> },
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
            ) : (
              <Empty>
                No treasury snapshot yet. Run <code>zl revalue</code> or wait for the worker.
              </Empty>
            )}
            <p className="footnote">
              <Link href="/treasury">Capital accounting, funding events, withdrawals and snapshots →</Link>
            </p>
          </div>
          <div>
            <h3>System</h3>
            <KV
              ariaLabel="System state"
              rows={[
                { label: "State", value: <Chip tone={status.mode.paused ? "red" : "green"}>{status.mode.paused ? "PAUSED" : "ONLINE"}</Chip> },
                { label: "Execution", value: <Chip tone={status.mode.live_trading ? "green" : "amber"}>{status.mode.execution_mode.replace("_", " ")}</Chip> },
                { label: "Treasury source", value: status.mode.treasury_mode },
                { label: "Active strategies", value: `${status.counts.active_strategies + status.counts.watch_strategies} / ${status.counts.strategies}` },
                { label: "Last rebalance", value: fmtTime(status.system.last_cycle_at) },
                { label: "Next cycle", value: `${fmtTime(status.system.next_cycle_at)} · ${fmtUntil(status.system.next_cycle_at)}` },
                { label: "Cycle time", value: `${status.system.cycle_time_et} ET, after the close` },
                { label: "Last completed session", value: status.system.last_completed_session },
                { label: "Market data", value: fmtTime(status.system.last_market_data_at) },
                { label: "Universe refresh", value: fmtTime(status.system.last_universe_refresh_at) },
                {
                  label: "Reconciliation",
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
                {
                  label: "Live trading blockers",
                  prose: true,
                  value: status.live_trading_blockers.length ? (
                    <span className="mono" style={{ fontSize: 12, lineHeight: 1.7 }}>
                      {status.live_trading_blockers.join(" · ")}
                    </span>
                  ) : (
                    <span className="pos">none — live trading is armed</span>
                  ),
                },
              ]}
            />
          </div>
        </div>
      </Section>

      <Section id="sleeves" title="Strategy sleeves" note="weights are shares of deployable capital (NAV minus the cash reserve) · returns are time-weighted">
        {strategies ? <StrategyTable strategies={strategies} /> : <Empty>Strategies unavailable.</Empty>}
        <p className="footnote">
          Each strategy is a virtual book inside the one treasury; no strategy has a wallet. <Link href="/strategies">Rules, parameters and per-strategy tear sheets →</Link>
        </p>
      </Section>

      <Section id="holdings" title="Holdings" note="Σ of the sleeve books · raw Stock Token units · valued at Robinhood mid × multiplier">
        {positionsCount === 0 ? (
          <Empty>No positions. The treasury is in cash.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data">
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
                        <td className="muted mono">{tp ? `${tp.price_source}${tp.stale === "true" ? " · stale" : ""}` : "—"}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="signals" title="Recent signals" note="SIGNAL — a strategy's target before netting">
        <SignalTable signals={(signals ?? []).slice(0, 20)} />
      </Section>

      <Section id="crosses" title="Internal crosses" note="INTERNAL_CROSS — netted between two sleeves inside the treasury; no blockchain transaction">
        <CrossTable crosses={crosses ?? []} />
      </Section>

      <Section id="executions" title="Executions" note="ONCHAIN_EXECUTION or DRY RUN — the net external change per asset after netting">
        <ExecutionTable executions={(executions ?? []).slice(0, 12)} compact />
        <p className="footnote">
          <Link href="/executions">Full execution ledger and blockchain transactions →</Link>
        </p>
      </Section>

      <Section id="reconciliation" title="Reconciliation" note={lastRecon ? `${lastRecon.details.trigger ?? ""} · ${fmtAge(lastRecon.run_at)}` : "never"}>
        <div className="cols even">
          {lastRecon ? (
            <KV
              ariaLabel="Reconciliation"
              rows={[
                { label: "Status", value: <Chip tone={statusClass(lastRecon.status)}>{lastRecon.status}</Chip> },
                { label: "Lines compared", value: String(lastRecon.details.lines?.length ?? 0) },
                { label: "Max deviation", value: `${Number(lastRecon.max_break_bps).toFixed(2)} bps · tolerance ${lastRecon.tolerance_bps}` },
                { label: "Sleeve cash / treasury cash", value: `${fmtMoney(lastRecon.details.sleeve_cash)} / ${fmtMoney(lastRecon.details.treasury_cash)}` },
                { label: "Reserve buffer", value: `${fmtMoney(lastRecon.details.buffer_cash)} · target ${fmtMoney(lastRecon.details.reserve_target)}` },
                { label: "Position breaks", value: <span className={lastRecon.position_breaks.length ? "neg" : ""}>{lastRecon.position_breaks.length}</span> },
                { label: "Auto-pause triggered", value: lastRecon.triggered_pause ? <span className="neg">yes</span> : "no" },
              ]}
            />
          ) : (
            <Empty>No reconciliation has run yet.</Empty>
          )}
          <p className="footnote" style={{ margin: 0 }}>
            After every execution and every hour, Σ sleeve positions must equal the treasury&apos;s positions per asset and Σ sleeve cash must not exceed treasury cash, within {lastRecon?.tolerance_bps ?? 10} bps of NAV per line. The cash no sleeve owns is the reserve buffer. A break is recorded as RECONCILIATION_FAILED and pauses live trading automatically. <Link href="/treasury#reconciliation">History →</Link>
          </p>
        </div>
      </Section>

      <Section id="log" title="System log" note="the engine's own events, live · nothing is narrated">
        <EventFeed initial={events ?? []} limit={150} height={420} />
        <p className="footnote">
          {status.counts.real_transactions === 0
            ? "No onchain transactions have been broadcast by this deployment. Rows marked DRY RUN are simulated fills with local identifiers; they are not blockchain activity."
            : `${status.counts.real_transactions} onchain transaction(s) recorded; each links to the Robinhood Chain explorer.`}{" "}
          <Link href="/events">Full log →</Link>
        </p>
      </Section>
    </div>
  );
}
