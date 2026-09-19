import { api, settle } from "@/lib/api";
import { fmtEth, fmtInt, fmtMoney, fmtTime, statusClass } from "@/lib/format";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Chip } from "@/components/Chip";
import { ExecutionTable } from "@/components/ExecutionTable";
import { ReportTitle } from "@/components/ReportTitle";
import { Empty, Section } from "@/components/Section";
import { TxLink } from "@/components/TxLink";
import { Unavailable } from "@/components/Unavailable";

export default async function ExecutionsPage() {
  const [status, executions, transactions] = await Promise.all([settle(api.status()), settle(api.executions(500)), settle(api.transactions(500))]);
  if (!status || !executions) {
    return (
      <div className="page">
        <ReportTitle kicker="ZIPLINE · execution ledger" title="Executions" status={status} />
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
  return (
    <div className="page">
      <AutoRefresh seconds={60} />
      <ReportTitle
        kicker="ZIPLINE · execution ledger"
        title="Executions"
        sub="every net external order"
        lede="Requested versus executed amounts, the effective price, slippage against the Robinhood reference, gas, and — for real trades — the Robinhood Chain transaction hash. Internal crosses never appear here because they never touch the chain."
        facts={[
          <>
            orders <b>{fmtInt(executions.length)}</b>
          </>,
          <>
            onchain <b>{fmtInt(live.length)}</b> · transactions <b>{fmtInt(transactions?.length ?? 0)}</b>
          </>,
          <>
            dry run <b>{fmtInt(dry.length)}</b>
          </>,
          <>
            filled <b>{fmtInt(filled.length)}</b> · rejected/failed <b>{fmtInt(rejected.length)}</b>
          </>,
          <>
            filled notional <b>{fmtMoney(gross)}</b>
          </>,
          <>
            gas <b>{fmtEth(gasEth, 6)}</b>
          </>,
        ]}
        status={status}
      />

      <Section id="transactions" title="Blockchain transactions" note="only transactions actually broadcast to Robinhood Chain appear here">
        {!transactions || transactions.length === 0 ? (
          <Empty>No transactions have been broadcast by this deployment. Dry-run orders below carry local identifiers and no hash.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="data">
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
      </Section>

      <Section id="orders" title="Orders" note={`${executions.length} rows · newest first`}>
        <ExecutionTable executions={executions} />
      </Section>
    </div>
  );
}
