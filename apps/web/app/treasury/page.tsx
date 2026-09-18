import { api, settle } from "@/lib/api";
import { fmtEth, fmtMoney, fmtTime, statusClass } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { NavCurve } from "@/components/Curves";
import { KV } from "@/components/KV";
import { Panel, Empty } from "@/components/Panel";
import { Money, Pct } from "@/components/Signed";
import { Tabs } from "@/components/Tabs";
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
      <div className="container">
        <div className="report-head">
          <h1>Treasury</h1>
        </div>
        <Unavailable />
      </div>
    );
  }
  const snap = treasury.snapshot;
  const hist = history ?? [];

  const fundingTab = (
    <div className="grid-2">
      <Panel title="Funding events" meta="deposits are never profit; new deployable capital is split across active sleeves, the reserve share stays at treasury level" flush>
        {!funding || funding.funding.length === 0 ? (
          <Empty>No funding events.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
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
      </Panel>
      <Panel title="Withdrawals" meta="operator-initiated · reduce NAV, never shown as a loss" flush>
        {!funding || funding.withdrawals.length === 0 ? (
          <Empty>No withdrawals.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
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
      </Panel>
    </div>
  );

  const reconTab = (
    <Panel title="Reconciliation history" meta="books vs treasury after every execution and on a schedule · a break pauses live trading" flush id="reconciliation">
      {!recon || recon.length === 0 ? (
        <Empty>No reconciliation runs yet.</Empty>
      ) : (
        <div className="tablewrap">
          <table className="table">
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
    </Panel>
  );

  const snapshotsTab = (
    <Panel title="Valuation snapshots" meta={`${hist.length} rows · newest first`} flush>
      {hist.length === 0 ? (
        <Empty>No snapshots yet.</Empty>
      ) : (
        <div className="tablewrap" style={{ maxHeight: 520 }}>
          <table className="table dense">
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
    </Panel>
  );

  return (
    <div className="container">
      <AutoRefresh seconds={60} />
      <div className="report-head">
        <div>
          <h1>
            Treasury <span className="sub">— one wallet, one pool of capital</span>
          </h1>
          <div className="meta">
            source <code>{snap?.mode ?? status.mode.treasury_mode}</code> · wallet{" "}
            {treasury.wallet_address ? (
              <a href={treasury.explorer_address_url ?? "#"} target="_blank" rel="noopener noreferrer">
                <code>{treasury.wallet_address}</code> ↗
              </a>
            ) : (
              <span>not configured</span>
            )}{" "}
            · cash token <code>{treasury.cash_token.symbol}</code>
            {treasury.cash_token.address ? <> <code>{treasury.cash_token.address}</code></> : null} · gas in ETH, reported separately
          </div>
        </div>
      </div>

      <div className="grid-2">
        <Panel title="Capital accounting" meta={snap ? `snapshot ${fmtTime(snap.taken_at)}` : undefined} flush>
          {snap ? (
            <div className="body">
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
            </div>
          ) : (
            <Empty>No treasury snapshot yet.</Empty>
          )}
        </Panel>
        <Panel title="NAV" meta="every valuation snapshot · contributions and withdrawals move this line; returns do not count them">
          <NavCurve history={hist} />
        </Panel>
      </div>

      <Tabs
        tabs={[
          { id: "funding", label: "Funding", count: funding?.funding.length ?? 0, content: fundingTab },
          { id: "reconciliation", label: "Reconciliation", count: recon?.length ?? 0, content: reconTab },
          { id: "snapshots", label: "Snapshots", count: hist.length, content: snapshotsTab },
        ]}
      />
    </div>
  );
}
