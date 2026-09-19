import type { Metrics, PortfolioSnapshot, TreasurySnapshot } from "@/lib/types";
import { PerfChart, type Series } from "./PerfChart";

const NAVY = "#1f4e79";
const BENCH = "#9a9a9a";
const RED = "#b42318";

function Figure({ title, caption, legend, children }: { title: string; caption?: string; legend?: { name: string; color: string }[]; children: React.ReactNode }) {
  return (
    <figure className="figure" aria-label={title}>
      <div className="legend">
        <span style={{ color: "var(--ink)", fontWeight: 500 }}>{title}</span>
        {legend?.map((l) => (
          <span key={l.name}>
            <span className="sw" style={{ background: l.color }} />
            {l.name}
          </span>
        ))}
      </div>
      {children}
      {caption ? <figcaption className="caption">{caption}</figcaption> : null}
    </figure>
  );
}

/** Cumulative returns vs benchmark; intraday valuations until the first session completes. */
export function CumulativeReturns({ metrics, label = "Algorithm" }: { metrics: Metrics | null; label?: string }) {
  if (!metrics) return <div className="empty">Metrics unavailable.</div>;
  const daily = metrics.cumulative;
  const series: Series[] = [];
  let caption: string;
  if (daily.length >= 2) {
    series.push({ name: label, color: NAVY, points: daily.map((p, i) => ({ x: i, y: p.algorithm, label: p.date })) });
    if (daily.filter((p) => p.benchmark !== undefined).length >= 2) series.push({ name: `Benchmark (${metrics.benchmark})`, color: BENCH, width: 1.2, points: daily.map((p, i) => ({ x: i, y: p.benchmark ?? 0, label: p.date })) });
    caption = `${daily.length} sessions. Time-weighted; contributions and withdrawals are flows, not returns.`;
  } else {
    series.push({ name: `${label} · intraday valuations`, color: NAVY, points: metrics.intraday.map((p, i) => ({ x: i, y: p.algorithm, label: p.t.replace("T", " ").slice(0, 16) + "Z" })) });
    caption = "No completed session yet: each point is a valuation at the live Robinhood mid. The benchmark line appears with the first completed session.";
  }
  return (
    <Figure title="Cumulative returns" legend={series.map((s) => ({ name: s.name, color: s.color }))} caption={caption}>
      <PerfChart series={series} height={280} emptyText="The curve appears after the second valuation." />
    </Figure>
  );
}

/** Underwater plot: drawdown from the running peak, filled. */
export function Underwater({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) return null;
  const dd = metrics.drawdowns;
  const points = dd.length >= 2 ? dd.map((p, i) => ({ x: i, y: p.drawdown, label: p.date })) : [];
  if (points.length < 2 && metrics.intraday.length >= 2) {
    // intraday drawdown from the running peak of the valuations
    let peak = -Infinity;
    metrics.intraday.forEach((p, i) => {
      peak = Math.max(peak, p.algorithm);
      const base = 1 + peak / 100;
      const cur = 1 + p.algorithm / 100;
      points.push({ x: i, y: (cur / base - 1) * 100, label: p.t.replace("T", " ").slice(0, 16) + "Z" });
    });
  }
  return (
    <Figure title="Underwater plot" caption="Drawdown from the running peak of the time-weighted index.">
      <PerfChart series={[{ name: "Drawdown", color: RED, width: 1.2, fill: true, points }]} height={150} emptyText="Appears after the second valuation." />
    </Figure>
  );
}

/** Daily returns as a thin bar-like plot (rendered as a step series). */
export function DailyReturns({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) return null;
  if (metrics.daily_returns.length < 2) {
    return (
      <p className="footnote" style={{ fontStyle: "italic" }}>
        Daily and monthly return plots appear after the first completed session; every statistic in the table is computed from those sessions only.
      </p>
    );
  }
  const pts = metrics.daily_returns.map((p, i) => ({ x: i, y: p.value, label: p.date }));
  return (
    <Figure title="Daily returns" caption="Close-to-close time-weighted return per completed session.">
      <PerfChart series={[{ name: "Daily return", color: NAVY, width: 1.2, points: pts }]} height={140} />
    </Figure>
  );
}

/** NAV in dollars over every valuation snapshot. */
export function NavPlot({ history, title = "Net asset value" }: { history: (TreasurySnapshot | PortfolioSnapshot)[]; title?: string }) {
  const pts = history.map((h, i) => ({ x: i, y: Number(h.nav), label: h.taken_at.replace("T", " ").slice(0, 16) + "Z" }));
  return (
    <Figure title={title} caption="Every valuation snapshot. Contributions and withdrawals move this line; returns do not count them.">
      <PerfChart series={[{ name: "NAV", color: NAVY, points: pts }]} height={220} format="money" baseline={false} emptyText="NAV history appears after the second valuation." />
    </Figure>
  );
}

/** Monthly returns grid (pyfolio's heatmap), rendered as a table once months exist. */
export function MonthlyReturns({ metrics }: { metrics: Metrics | null }) {
  if (!metrics || metrics.monthly.length === 0) return null;
  const years = Array.from(new Set(metrics.monthly.map((m) => m.year))).sort();
  const cell = (y: number, m: number) => metrics.monthly.find((r) => r.year === y && r.month === m)?.value ?? null;
  return (
    <Figure title="Monthly returns" caption="Compounded from daily time-weighted returns.">
      <div className="tablewrap">
        <table className="data dense">
          <thead>
            <tr>
              <th>Year</th>
              {["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].map((m) => (
                <th key={m} className="num">
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {years.map((y) => (
              <tr key={y}>
                <td>{y}</td>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                  const v = cell(y, m);
                  return (
                    <td key={m} className={`num ${v === null ? "faint" : v > 0 ? "pos" : v < 0 ? "neg" : ""}`}>
                      {v === null ? "—" : `${(v * 100).toFixed(1)}%`}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}
