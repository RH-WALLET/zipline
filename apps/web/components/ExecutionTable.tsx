import Link from "next/link";
import type { Execution } from "@/lib/types";
import { fmtBps, fmtEth, fmtMoney, fmtPrice, fmtQty, fmtTime, statusClass } from "@/lib/format";
import { Chip } from "./Chip";
import { TxLink } from "./TxLink";

/**
 * The execution ledger. Every row is a net external order. LIVE rows carry a real hash and an
 * explorer link; DRY_RUN rows carry a local id (dry-000042) and no hash, by construction.
 * Paired facts share a cell (executed over requested, effective over reference) so the ledger
 * reads at report width without a horizontal scrollbar.
 */
export function ExecutionTable({ executions, compact = false }: { executions: Execution[]; compact?: boolean }) {
  if (executions.length === 0) return <p className="footnote" style={{ fontStyle: "italic" }}>No executions yet.</p>;
  return (
    <div className="tablewrap">
      <table className="data">
        <thead>
          <tr>
            <th>
              Time <span className="sub">UTC</span>
            </th>
            <th>
              Order <span className="sub">mode</span>
            </th>
            <th>Side · asset</th>
            <th className="num">
              Executed <span className="sub">requested</span>
            </th>
            <th className="num">Notional</th>
            <th className="num">
              Price <span className="sub">reference</span>
            </th>
            <th className="num">
              Slippage {!compact ? <span className="sub">impact</span> : null}
            </th>
            <th className="num">Gas</th>
            <th>Transaction</th>
            <th>Status</th>
            {!compact ? (
              <th>
                Attribution <span className="sub">sleeves</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {executions.map((e) => {
            const swap = e.transactions.find((t) => t.kind === "SWAP") ?? e.transactions[0];
            const live = e.mode === "LIVE";
            return (
              <tr key={e.id}>
                <td className="mono muted">
                  {fmtTime(e.created_at).slice(0, 10)}
                  <span className="sub">{fmtTime(e.created_at).slice(11)}</span>
                </td>
                <td className="mono">
                  {e.cycle_id ? <Link href={`/cycles/${e.cycle_id}`}>{e.local_id}</Link> : e.local_id}
                  <span className="sub">
                    <Chip tone={live ? "green" : "amber"}>{live ? "ONCHAIN" : "DRY RUN"}</Chip>
                  </span>
                </td>
                <td>
                  <span className={`mono ${e.side === "BUY" ? "pos" : "neg"}`}>{e.side}</span> <span className="sym">{e.symbol ?? "—"}</span>
                </td>
                <td className="num">
                  {e.executed_quantity ? fmtQty(e.executed_quantity) : <span className="muted">—</span>}
                  <span className="sub">req {fmtQty(e.requested_quantity)}</span>
                </td>
                <td className="num">{fmtMoney(e.executed_notional ?? e.requested_notional)}</td>
                <td className="num">
                  {fmtPrice(e.effective_price)}
                  <span className="sub">ref {fmtPrice(e.reference_price)}</span>
                </td>
                <td className="num">
                  {fmtBps(e.slippage_bps)}
                  {!compact ? <span className="sub">{e.price_impact_bps === null ? "impact n/a" : `impact ${fmtBps(e.price_impact_bps)}`}</span> : null}
                </td>
                <td className="num">{e.gas_cost_eth ? fmtEth(e.gas_cost_eth) : <span className="muted">{live ? "—" : "none"}</span>}</td>
                <td>
                  {swap ? (
                    <>
                      <TxLink hash={swap.tx_hash} url={swap.explorer_url} />
                      {swap.block_number ? <span className="sub">block {swap.block_number}</span> : null}
                    </>
                  ) : (
                    <span className="muted">{live ? "—" : "no tx (dry run)"}</span>
                  )}
                </td>
                <td>
                  <Chip tone={statusClass(e.status)}>{e.status.replace("_", " ")}</Chip>
                  {e.reject_reason ? <div className="muted small wrap" style={{ whiteSpace: "normal", maxWidth: "32ch" }}>{e.reject_reason}</div> : null}
                </td>
                {!compact ? (
                  <td className="mono muted wrap" style={{ minWidth: "18ch", maxWidth: "26ch" }} title={e.contributions.map((c) => `${c.strategy} ${Number(c.quantity).toFixed(6)}`).join("\n")}>
                    {e.contributions.map((c) => c.strategy).join(", ") || "—"}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
