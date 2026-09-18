import type { Metrics, MetricSet } from "@/lib/types";

type Tone = "pos" | "neg" | "na" | undefined;
type Cell = { label: string; value: string; tone?: Tone; sub?: string };

function pct(v: number | null | undefined, signed = true): { value: string; tone: Tone } {
  if (v === null || v === undefined) return { value: "—", tone: "na" };
  const p = v * 100;
  const value = `${signed && p > 0 ? "+" : p < 0 ? "−" : ""}${Math.abs(p).toFixed(2)}%`;
  return { value, tone: signed ? (p > 0 ? "pos" : p < 0 ? "neg" : undefined) : undefined };
}

function ratio(v: number | null | undefined, digits = 2): { value: string; tone: Tone } {
  if (v === null || v === undefined) return { value: "—", tone: "na" };
  return { value: v.toFixed(digits), tone: undefined };
}

/** Quantopian's backtest header: nine statistics, computed by empyrical. Null = not enough history, shown as —. */
export function StatsStrip({ metrics, totalReturnPct }: { metrics: Metrics | null; totalReturnPct?: string | number | null }) {
  const m: MetricSet | null = metrics?.overall ?? null;
  const sessions = metrics?.sessions ?? 0;
  const tr = totalReturnPct !== undefined && totalReturnPct !== null ? Number(totalReturnPct) / 100 : m?.total_return ?? null;
  const cells: Cell[] = [
    { label: "Total returns", ...pct(tr), sub: sessions ? `${sessions} sessions` : "since inception" },
    { label: "Benchmark returns", ...pct(m?.benchmark_return), sub: metrics?.benchmark ?? "SPY" },
    { label: "Alpha", ...ratio(m?.alpha, 3), sub: "annualized" },
    { label: "Beta", ...ratio(m?.beta) },
    { label: "Sharpe", ...ratio(m?.sharpe) },
    { label: "Sortino", ...ratio(m?.sortino) },
    { label: "Information ratio", ...ratio(m?.information_ratio) },
    { label: "Volatility", ...pct(m?.volatility, false), sub: "annualized" },
    { label: "Max drawdown", ...pct(m?.max_drawdown, false), tone: m?.max_drawdown ? "neg" : "na" },
  ];
  return (
    <div className="stats" role="list" aria-label="Performance statistics">
      {cells.map((c) => (
        <div className="stat" role="listitem" key={c.label}>
          <div className="label">{c.label}</div>
          <div className={`value ${c.tone ?? ""}`}>{c.value}</div>
          <div className="sub">{c.sub ?? (c.tone === "na" ? "needs more history" : " ")}</div>
        </div>
      ))}
    </div>
  );
}

export function RiskTable({ metrics }: { metrics: Metrics | null }) {
  const rows: [string, keyof MetricSet, "pct" | "ratio"][] = [
    ["Returns", "total_return", "pct"],
    ["Benchmark returns", "benchmark_return", "pct"],
    ["Alpha", "alpha", "ratio"],
    ["Beta", "beta", "ratio"],
    ["Sharpe", "sharpe", "ratio"],
    ["Sortino", "sortino", "ratio"],
    ["Information ratio", "information_ratio", "ratio"],
    ["Volatility", "volatility", "pct"],
    ["Max drawdown", "max_drawdown", "pct"],
  ];
  const windows = ["1M", "3M", "6M", "12M"] as const;
  const fmt = (v: number | null | undefined, kind: "pct" | "ratio") => (kind === "pct" ? pct(v, false).value : ratio(v).value);
  return (
    <div className="tablewrap">
      <table className="table dense">
        <thead>
          <tr>
            <th>Risk metrics</th>
            {windows.map((w) => (
              <th key={w} className="num">
                {w.replace("M", " Month")}
              </th>
            ))}
            <th className="num">Overall</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key, kind]) => (
            <tr key={key}>
              <td>{label}</td>
              {windows.map((w) => {
                const set = metrics?.windows?.[w] ?? null;
                return (
                  <td key={w} className={`num ${set ? "" : "muted"}`}>
                    {set ? fmt(set[key], kind) : "—"}
                  </td>
                );
              })}
              <td className="num">{fmt(metrics?.overall?.[key], kind)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="help">Windows fill in once 21 / 63 / 126 / 252 completed sessions exist. Returns are time-weighted; the benchmark is SPY&apos;s underlying close-to-close; statistics by empyrical-reloaded.</p>
    </div>
  );
}
