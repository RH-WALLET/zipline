import type { ReactNode } from "react";

export type KVRow = { label: ReactNode; value: ReactNode; big?: boolean; left?: boolean };

/** Key/value ledger: label left, tabular value right. */
export function KV({ rows, ariaLabel }: { rows: KVRow[]; ariaLabel?: string }) {
  return (
    <dl className="kv" aria-label={ariaLabel}>
      {rows.map((r, i) => (
        <div key={i}>
          <dt>{r.label}</dt>
          <dd className={`${r.big ? "big" : ""} ${r.left ? "left" : ""}`}>{r.value}</dd>
        </div>
      ))}
    </dl>
  );
}
