import Link from "next/link";
import type { Execution } from "@/lib/types";
import { fmtBps, fmtEth, fmtMoney, fmtPrice, fmtQty, fmtTime, statusClass } from "@/lib/format";
import { Chip } from "./Chip";
import { TxLink } from "./TxLink";

/**
 * The execution ledger. Every row is a net external order. LIVE rows carry a real hash and an
 * explorer link; DRY_RUN rows carry a local id (dry-000042) and no hash, by construction.
 */
export function ExecutionTable({ executions, compact = false }: { executions: Execution[]; compact?: boolean }) {
  if (executions.length === 0) return <p className="help" style={{ padding: 16 }}>No executions yet.</p>;
  return (
    <div className="tablewrap">
      <table className="table">
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Id</th>
            <th>Mode</th>
            <th>Asset</th>
            <th>Side</th>
            <th className="num">Requested</th>
            <th className="num">Executed</th>
            <th className="num">Notional</th>
            <th className="num">Ref price</th>
            <th className="num">Eff. price</th>
            <th className="num">Slippage</th>
            {!compact ? <th className="num">Impact</th> : null}
            <th className="num">Gas</th>
            <th>Tx hash</th>
            {!compact ? <th className="num">Block</th> : null}
            <th>Status</th>
            {!compact ? <th>Attribution</th> : null}
          </tr>
        </thead>
        <tbody>
          {executions.map((e) => {
            const swap = e.transactions.find((t) => t.kind === "SWAP") ?? e.transactions[0];
            return (
              <tr key={e.id}>
                <td className="mono muted">{fmtTime(e.created_at)}</td>
                <td className="mono">{e.cycle_id ? <Link href={`/cycles/${e.cycle_id}`}>{e.local_id}</Link> : e.local_id}</td>
                <td>
                  <Chip tone={e.mode === "LIVE" ? "green" : "amber"}>{e.mode === "LIVE" ? "ONCHAIN" : "DRY RUN"}</Chip>
                </td>
                <td>
                  <span className="sym">{e.symbol ?? "—"}</span>
                </td>
                <td className={e.side === "BUY" ? "pos" : "neg"}>{e.side}</td>
                <td className="num">{fmtQty(e.requested_quantity)}</td>
                <td className="num">{e.executed_quantity ? fmtQty(e.executed_quantity) : <span className="muted">—</span>}</td>
                <td className="num">{fmtMoney(e.executed_notional ?? e.requested_notional)}</td>
                <td className="num muted">{fmtPrice(e.reference_price)}</td>
                <td className="num">{fmtPrice(e.effective_price)}</td>
                <td className="num">{fmtBps(e.slippage_bps)}</td>
                {!compact ? <td className="num">{e.price_impact_bps === null ? <span className="muted">n/a</span> : fmtBps(e.price_impact_bps)}</td> : null}
                <td className="num">{e.gas_cost_eth ? fmtEth(e.gas_cost_eth) : <span className="muted">{e.mode === "LIVE" ? "—" : "none"}</span>}</td>
                <td>{swap ? <TxLink hash={swap.tx_hash} url={swap.explorer_url} /> : <span className="muted">{e.mode === "LIVE" ? "—" : "no tx (dry run)"}</span>}</td>
                {!compact ? <td className="num muted">{swap?.block_number ?? "—"}</td> : null}
                <td>
                  <Chip tone={statusClass(e.status)}>{e.status.replace("_", " ")}</Chip>
                  {e.reject_reason ? <div className="muted small wrap" style={{ whiteSpace: "normal", maxWidth: "36ch" }}>{e.reject_reason}</div> : null}
                </td>
                {!compact ? <td className="mono muted">{e.contributions.map((c) => `${c.strategy} ${Number(c.quantity).toFixed(4)}`).join(" · ")}</td> : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
