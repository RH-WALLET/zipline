import type { Metrics, MetricSet } from "@/lib/types";

type Row = { label: string; key: keyof MetricSet; kind: "pct" | "ratio" | "num" };

const ROWS: (Row | { group: string })[] = [
  { group: "Returns" },
  { label: "Annual return", key: "annual_return", kind: "pct" },
  { label: "Cumulative returns", key: "total_return", kind: "pct" },
  { label: "Benchmark cumulative returns", key: "benchmark_return", kind: "pct" },
  { label: "Annual volatility", key: "volatility", kind: "pct" },
  { group: "Risk-adjusted" },
  { label: "Sharpe ratio", key: "sharpe", kind: "ratio" },
  { label: "Calmar ratio", key: "calmar", kind: "ratio" },
  { label: "Stability", key: "stability", kind: "ratio" },
  { label: "Max drawdown", key: "max_drawdown", kind: "pct" },
  { label: "Omega ratio", key: "omega", kind: "ratio" },
  { label: "Sortino ratio", key: "sortino", kind: "ratio" },
  { group: "Distribution" },
  { label: "Skew", key: "skew", kind: "num" },
  { label: "Kurtosis", key: "kurtosis", kind: "num" },
  { label: "Tail ratio", key: "tail_ratio", kind: "ratio" },
  { label: "Daily value at risk", key: "daily_var", kind: "pct" },
  { group: "Versus benchmark" },
  { label: "Alpha", key: "alpha", kind: "num" },
  { label: "Beta", key: "beta", kind: "num" },
  { label: "Information ratio", key: "information_ratio", kind: "ratio" },
];

export function fmtStat(v: number | null | undefined, kind: "pct" | "ratio" | "num"): string {
  if (v === null || v === undefined) return "—";
  if (kind === "pct") {
    const p = v * 100;
    return `${p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toFixed(2)}%`;
  }
  return `${v < 0 ? "−" : ""}${Math.abs(v).toFixed(kind === "ratio" ? 2 : 3)}`;
}

/**
 * pyfolio's perf_stats table, set as a tear sheet: a hero figure, then grouped statistics.
 * Every value is computed by empyrical from the engine's valuations; "—" means not enough history.
 */
export function PerfStats({ metrics, heroLabel = "Total return", heroPct }: { metrics: Metrics | null; heroLabel?: string; heroPct?: string | number | null }) {
  const m = metrics?.overall ?? null;
  const hero = heroPct !== undefined && heroPct !== null ? Number(heroPct) / 100 : m?.total_return ?? null;
  const missing = m ? Object.values(m).filter((v) => v === null).length : ROWS.length;
  return (
    <div>
      <table className="stats" aria-label="Performance statistics">
        <tbody>
          <tr className="hero">
            <th scope="row">{heroLabel}</th>
            <td className={hero === null ? "na" : hero > 0 ? "pos" : hero < 0 ? "neg" : ""}>{fmtStat(hero, "pct")}</td>
          </tr>
          {ROWS.map((r, i) =>
            "group" in r ? (
              <tr className="group" key={`g${i}`}>
                <th scope="row" colSpan={2}>
                  {r.group}
                </th>
              </tr>
            ) : (
              <tr key={r.key}>
                <th scope="row">{r.label}</th>
                <td className={m?.[r.key] === null || m?.[r.key] === undefined ? "na" : ""}>{fmtStat(m?.[r.key], r.kind)}</td>
              </tr>
            ),
          )}
        </tbody>
      </table>
      <p className="footnote">
        {metrics ? `${metrics.sessions} completed session${metrics.sessions === 1 ? "" : "s"} of time-weighted returns; benchmark ${metrics.benchmark}.` : "Metrics unavailable."}
        {missing ? " — marks statistics that need more history than exists; nothing is estimated." : ""}
      </p>
    </div>
  );
}

/** Rolling-window table (1M / 3M / 6M / 12M) in the same shape as the backtest report's risk table. */
export function RollingTable({ metrics }: { metrics: Metrics | null }) {
  const rows: Row[] = [
    { label: "Returns", key: "total_return", kind: "pct" },
    { label: "Benchmark returns", key: "benchmark_return", kind: "pct" },
    { label: "Alpha", key: "alpha", kind: "num" },
    { label: "Beta", key: "beta", kind: "num" },
    { label: "Sharpe", key: "sharpe", kind: "ratio" },
    { label: "Sortino", key: "sortino", kind: "ratio" },
    { label: "Volatility", key: "volatility", kind: "pct" },
    { label: "Max drawdown", key: "max_drawdown", kind: "pct" },
  ];
  const windows = ["1M", "3M", "6M", "12M"] as const;
  return (
    <div className="tablewrap">
      <table className="data dense">
        <thead>
          <tr>
            <th>Window</th>
            {windows.map((w) => (
              <th key={w} className="num">
                {w}
              </th>
            ))}
            <th className="num">All</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td>{r.label}</td>
              {windows.map((w) => {
                const set = metrics?.windows?.[w] ?? null;
                return (
                  <td key={w} className={`num ${set ? "" : "faint"}`}>
                    {set ? fmtStat(set[r.key], r.kind) : "—"}
                  </td>
                );
              })}
              <td className="num">{fmtStat(metrics?.overall?.[r.key], r.kind)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="footnote">Windows fill in at 21, 63, 126 and 252 completed sessions.</p>
    </div>
  );
}
