import Link from "next/link";
import type { Signal } from "@/lib/types";
import { fmtTime, fmtWeight } from "@/lib/format";

function summarize(details: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(details)) {
    if (k === "universe" || k === "targets" || k === "previous") continue;
    if (typeof v === "number") parts.push(`${k}=${Number.isInteger(v) ? v : v.toFixed(4)}`);
    else if (typeof v === "boolean") parts.push(`${k}=${v}`);
    else if (typeof v === "string" && v.length < 24) parts.push(`${k}=${v}`);
    else if (Array.isArray(v) && v.length < 5) parts.push(`${k}=${v.join("|")}`);
  }
  return parts.slice(0, 6).join("  ");
}

export function SignalTable({ signals, showStrategy = true }: { signals: Signal[]; showStrategy?: boolean }) {
  if (signals.length === 0) return <p className="help" style={{ padding: 16 }}>No signals yet — run a cycle.</p>;
  return (
    <div className="tablewrap">
      <table className="table">
        <thead>
          <tr>
            <th>Time (UTC)</th>
            <th>Session</th>
            {showStrategy ? <th>Strategy</th> : null}
            <th>Asset</th>
            <th>Kind</th>
            <th className="num">Value</th>
            <th className="num">Prev → Target</th>
            <th>Version</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.id}>
              <td className="mono muted">{fmtTime(s.created_at)}</td>
              <td className="mono muted">{s.session_date}</td>
              {showStrategy ? (
                <td>
                  <Link href={`/strategies/${s.strategy}`}>{s.strategy}</Link>
                </td>
              ) : null}
              <td>{s.symbol ? <span className="sym">{s.symbol}</span> : <span className="muted">portfolio</span>}</td>
              <td className="mono">{s.kind}</td>
              <td className="num">{s.value === null ? <span className="muted">—</span> : Number(s.value).toFixed(4)}</td>
              <td className="num">
                {s.symbol || s.kind === "TARGETS" ? (
                  <>
                    <span className="muted">{fmtWeight(s.previous_weight)}</span> → {fmtWeight(s.target_weight)}
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="mono muted">{s.version_hash.slice(0, 8)}</td>
              <td className="mono muted">{summarize(s.details)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
