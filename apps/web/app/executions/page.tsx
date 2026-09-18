import { api, settle } from "@/lib/api";
import { fmtEth, fmtInt, fmtMoney, fmtTime, statusClass } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { ExecutionTable } from "@/components/ExecutionTable";
import { Panel, Empty } from "@/components/Panel";
import { Tabs } from "@/components/Tabs";
import { TxLink } from "@/components/TxLink";
import { Unavailable } from "@/components/Unavailable";

export default async function ExecutionsPage() {
  const [status, executions, transactions] = await Promise.all([settle(api.status()), settle(api.executions(500)), settle(api.transactions(500))]);
  if (!status || !executions) {
    return (
      <div className="container">
        <div className="report-head">
          <h1>Execution ledger</h1>
        </div>
        <Unavailable />
      </div>
    );
  }
  const live = executions.filter((e) => e.mode === "LIVE");
  const dry = executions.filter((e) => e.mode !== "LIVE");
  const filled = executions.filter((e) => e.status === "CONFIRMED" || e.status === "DRY_RUN_FILLED");
  const rejected = executions.filter((e) => e.status === "REJECTED" || e.status === "FAILED");
  const gross = filled.reduce((a, e) => a + Number(e.executed_notional ?? 0), 0);
  const gasEth = (transactions ?? []).reduce((a, t) => a + Number(t.gas_cost_eth ?? 0), 0);
  const cells: [string, string, string?][] = [
    ["Orders", fmtInt(executions.length)],
    ["Onchain", fmtInt(live.length), `${fmtInt(transactions?.length ?? 0)} transactions`],
    ["Dry run", fmtInt(dry.length), "local ids, no hashes"],
    ["Filled", fmtInt(filled.length)],
    ["Rejected / failed", fmtInt(rejected.length)],
    ["Filled notional", fmtMoney(gross)],
    ["Gas spent", fmtEth(gasEth, 6)],
  ];

  const txTable = (
    <Panel title="Blockchain transactions" meta="only transactions actually broadcast to Robinhood Chain appear here; each hash links to the explorer" flush>
      {!transactions || transactions.length === 0 ? (
        <Empty>No transactions have been broadcast by this deployment.</Empty>
      ) : (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <th>Submitted (UTC)</th>
                <th>Kind</th>
                <th>Tx hash</th>
                <th className="num">Block</th>
                <th>From</th>
                <th>To</th>
                <th className="num">Gas used</th>
                <th className="num">Gas cost</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((t) => (
                <tr key={t.id}>
                  <td className="mono muted">{fmtTime(t.submitted_at)}</td>
                  <td className="mono">{t.kind}</td>
                  <td>
                    <TxLink hash={t.tx_hash} url={t.explorer_url} />
                  </td>
                  <td className="num">{t.block_number ?? "—"}</td>
                  <td className="mono muted">{t.from_address.slice(0, 10)}…</td>
                  <td className="mono muted">{t.to_address.slice(0, 10)}…</td>
                  <td className="num">{fmtInt(t.gas_used)}</td>
                  <td className="num">
                    {fmtEth(t.gas_cost_eth)} {t.gas_cost_usd ? <span className="muted">≈ {fmtMoney(t.gas_cost_usd)}</span> : null}
                  </td>
                  <td>
                    <Chip tone={statusClass(t.status)}>{t.status}</Chip>
                    {t.error ? <div className="muted small">{t.error}</div> : null}
                  </td>
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
            Execution ledger <span className="sub">— every net external order</span>
          </h1>
          <div className="meta">requested vs executed amounts, effective price, slippage against the Robinhood reference, gas, and — for real trades — the Robinhood Chain transaction hash. Internal crosses never appear here because they never touch the chain.</div>
        </div>
      </div>
      <div className="stats" role="list" aria-label="Ledger totals">
        {cells.map(([label, value, sub]) => (
          <div className="stat" role="listitem" key={label}>
            <div className="label">{label}</div>
            <div className="value" style={{ fontSize: 20 }}>
              {value}
            </div>
            <div className="sub">{sub ?? " "}</div>
          </div>
        ))}
      </div>
      <Tabs
        tabs={[
          { id: "orders", label: "Orders", count: executions.length, content: <Panel title="Orders" meta="newest first" flush><ExecutionTable executions={executions} /></Panel> },
          { id: "transactions", label: "Blockchain transactions", count: transactions?.length ?? 0, content: txTable },
        ]}
      />
    </div>
  );
}
