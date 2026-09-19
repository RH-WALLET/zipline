import { api, settle } from "@/lib/api";
import { fmtEth, fmtMoney, fmtTime, statusClass } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { KV } from "@/components/KV";
import { ReportTitle } from "@/components/ReportTitle";
import { Contents, Empty, Section } from "@/components/Section";
import { Money, Pct } from "@/components/Signed";
import { NavPlot } from "@/components/TearPlots";
import { TxLink } from "@/components/TxLink";
import { Unavailable } from "@/components/Unavailable";

export default async function TreasuryPage() {
  const [status, treasury, history, funding, recon] = await Promise.all([
    settle(api.status()),
    settle(api.treasury()),
    settle(api.treasuryHistory(1000)),
    settle(api.funding()),
    settle(api.reconciliation(50)),
  ]);
  if (!status || !treasury) {
    return (
      <div className="page">
        <ReportTitle kicker="ZIPLINE · capital accounting" title="Capital" status={status} />
        <Unavailable />
      </div>
    );
  }
  const snap = treasury.snapshot;
  const hist = history ?? [];
  return (
    <div className="page">
      <AutoRefresh seconds={60} />
      <ReportTitle
        kicker="ZIPLINE · capital accounting"
        title="Capital"
        sub="one wallet, one pool"
        lede="Base capital and later contributions are external flows; only trading changes the time-weighted return. Withdrawals reduce NAV and are never shown as losses. Gas is paid in ETH and reported separately."
        facts={[
          <>
            source <b className="mono">{snap?.mode ?? status.mode.treasury_mode}</b>
          </>,
          <>
            wallet{" "}
            <b className="mono">
              {treasury.wallet_address ? (
                <a href={treasury.explorer_address_url ?? "#"} target="_blank" rel="noopener noreferrer">
                  {treasury.wallet_address} ↗
                </a>
              ) : (
                "not configured"
              )}
            </b>
          </>,
          <>
            cash token <b className="mono">{treasury.cash_token.symbol}</b> {treasury.cash_token.address ? <span className="mono">{treasury.cash_token.address}</span> : null}
          </>,
        ]}
        status={status}
      />
      <Contents
        items={[
          ["accounting", "Accounting"],
          ["funding", "Funding"],
          ["withdrawals", "Withdrawals"],
          ["reconciliation", "Reconciliation"],
          ["snapshots", "Snapshots"],
        ]}
      />

      <Section id="accounting" title="Capital accounting" note={snap ? `snapshot ${fmtTime(snap.taken_at)}` : undefined}>
        <div className="cols">
          {snap ? (
            <KV
              ariaLabel="Capital accounting"
              rows={[
                { label: "Current NAV", value: fmtMoney(snap.nav), big: true },
                { label: "Base capital", value: fmtMoney(snap.base_capital) },
                { label: "Additional contributions", value: fmtMoney(snap.contributions_total) },
                { label: "Withdrawals", value: fmtMoney(snap.withdrawals_total) },
                { label: "Net external capital", value: fmtMoney(treasury.returns.net_external_capital) },
                { label: "Trading PnL (NAV − net capital)", value: <Money v={treasury.returns.trading_pnl} sign /> },
                { label: "of which realized", value: <span className="muted">{fmtMoney(snap.realized_pnl, { sign: true })}</span> },
                { label: "of which unrealized", value: <span className="muted">{fmtMoney(snap.unrealized_pnl, { sign: true })}</span> },
                {
                  label: "Gas cost (ETH, separate)",
                  value: (
                    <>
                      {fmtEth(snap.cumulative_gas_eth)} <span className="muted">{Number(snap.cumulative_gas_usd) > 0 ? `≈ ${fmtMoney(snap.cumulative_gas_usd)}` : ""}</span>
                    </>
                  ),
                },
                { label: "Time-weighted return", value: <Pct v={treasury.returns.total_return_pct} /> },
                { label: "Simple return on net capital", value: <Pct v={treasury.returns.simple_return_pct} /> },
                { label: "Deployable capital", value: fmtMoney(snap.deployable_capital) },
                { label: "Cash reserve target", value: fmtMoney(snap.reserved_cash) },
              ]}
            />
          ) : (
            <Empty>No treasury snapshot yet.</Empty>
          )}
          <NavPlot history={hist} />
        </div>
      </Section>

      <Section id="funding" title="Funding events" note="deposits are never profit · new deployable capital is split across active sleeves; the reserve share stays at treasury level">
        {!funding || funding.funding.length === 0 ? (
          <Empty>No funding events.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Detected (UTC)</th>
                  <th>Kind</th>
                  <th className="num">Amount</th>
                  <th>Tx</th>
                  <th>Allocated</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {funding.funding.map((f) => (
                  <tr key={f.id}>
                    <td className="mono muted">{fmtTime(f.detected_at)}</td>
                    <td>
                      <Chip tone={f.kind === "DEMO_SEED" ? "amber" : "green"}>{f.kind.replace("_", " ")}</Chip>
                    </td>
                    <td className="num">
                      {fmtMoney(f.amount)} <span className="muted">{f.asset_symbol}</span>
                    </td>
                    <td>
                      <TxLink hash={f.tx_hash} url={f.explorer_url} />
                    </td>
                    <td className="muted small">{f.allocated ? `${Object.keys(f.allocation.to_sleeves ?? {}).length} sleeves · reserve ${fmtMoney(f.allocation.to_reserve ?? null)}` : "pending"}</td>
                    <td className="muted wrap">{f.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="withdrawals" title="Withdrawals" note="operator-initiated · reduce NAV, never shown as a loss">
        {!funding || funding.withdrawals.length === 0 ? (
          <Empty>No withdrawals.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Time (UTC)</th>
                  <th className="num">Amount</th>
                  <th>To</th>
                  <th>Tx</th>
                  <th>Status</th>
                  <th>Deallocation</th>
                </tr>
              </thead>
              <tbody>
                {funding.withdrawals.map((w) => (
                  <tr key={w.id}>
                    <td className="mono muted">{fmtTime(w.created_at)}</td>
                    <td className="num">{fmtMoney(w.amount)}</td>
                    <td className="mono muted">{w.to_address ?? "—"}</td>
                    <td>
                      <TxLink hash={w.tx_hash} url={w.explorer_url} />
                    </td>
                    <td>
                      <Chip tone={statusClass(w.status)}>{w.status}</Chip>
                    </td>
                    <td className="muted small wrap">
                      {Object.entries(w.deallocation)
                        .map(([k, v]) => `${k} ${fmtMoney(v)}`)
                        .join(", ") || "from buffer cash"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="reconciliation" title="Reconciliation history" note="books versus treasury after every execution and on a schedule · a break pauses live trading">
        {!recon || recon.length === 0 ? (
          <Empty>No reconciliation runs yet.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data dense">
              <thead>
                <tr>
                  <th>Run (UTC)</th>
                  <th>Trigger</th>
                  <th>Status</th>
                  <th className="num">Lines</th>
                  <th className="num">Max dev (bps)</th>
                  <th className="num">Tolerance</th>
                  <th className="num">Cash break</th>
                  <th className="num">Buffer cash</th>
                  <th>Breaks</th>
                  <th>Paused</th>
                </tr>
              </thead>
              <tbody>
                {recon.map((r) => (
                  <tr key={r.id}>
                    <td className="mono muted">{fmtTime(r.run_at)}</td>
                    <td className="muted">{r.details.trigger ?? "—"}</td>
                    <td>
                      <Chip tone={statusClass(r.status)}>{r.status === "RECONCILIATION_OK" ? "OK" : "FAILED"}</Chip>
                    </td>
                    <td className="num">{r.details.lines?.length ?? 0}</td>
                    <td className="num">{Number(r.max_break_bps).toFixed(2)}</td>
                    <td className="num muted">{r.tolerance_bps} bps</td>
                    <td className={`num ${Number(r.cash_break) !== 0 ? "neg" : "muted"}`}>{fmtMoney(r.cash_break)}</td>
                    <td className="num muted">{fmtMoney(r.details.buffer_cash)}</td>
                    <td className={`small ${r.position_breaks.length ? "neg" : "muted"}`}>{r.position_breaks.length ? r.position_breaks.map((b) => `${b.symbol} Δ${b.diff}`).join(", ") : "none"}</td>
                    <td className={r.triggered_pause ? "neg" : "muted"}>{r.triggered_pause ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section id="snapshots" title="Valuation snapshots" note={`${hist.length} rows · newest first`}>
        {hist.length === 0 ? (
          <Empty>No snapshots yet.</Empty>
        ) : (
          <div className="tablewrap" style={{ maxHeight: 520, overflowY: "auto" }}>
            <table className="data dense">
              <thead>
                <tr>
                  <th>Taken (UTC)</th>
                  <th className="num">NAV</th>
                  <th className="num">Cash</th>
                  <th className="num">Positions</th>
                  <th className="num">Realized</th>
                  <th className="num">Unrealized</th>
                  <th className="num">TWR</th>
                  <th className="num">Gas ETH</th>
                </tr>
              </thead>
              <tbody>
                {[...hist].reverse().map((h) => (
                  <tr key={h.id}>
                    <td className="mono muted">{fmtTime(h.taken_at)}</td>
                    <td className="num">{fmtMoney(h.nav)}</td>
                    <td className="num muted">{fmtMoney(h.cash_balance)}</td>
                    <td className="num muted">{fmtMoney(h.positions_value)}</td>
                    <td className="num">
                      <Money v={h.realized_pnl} sign />
                    </td>
                    <td className="num">
                      <Money v={h.unrealized_pnl} sign />
                    </td>
                    <td className="num">
                      <Pct v={(Number(h.twr_index) - 1) * 100} digits={3} />
                    </td>
                    <td className="num muted">{fmtEth(h.gas_balance_eth, 4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}
