import type { Metrics, PortfolioSnapshot, TreasurySnapshot } from "@/lib/types";
import { PerfChart, type Series } from "./PerfChart";

const BLUE = "#2a7ab8";
const GREY = "#9aa0a6";

/**
 * Cumulative performance: the time-weighted index vs SPY on session dates; before the first
 * full session exists, the intraday valuations are shown so the curve is never fictional.
 */
export function PerformanceCurve({ metrics, label = "Algorithm" }: { metrics: Metrics | null; label?: string }) {
  if (!metrics) return <div className="empty">Metrics unavailable.</div>;
  const daily = metrics.cumulative;
  const series: Series[] = [];
  if (daily.length >= 2) {
    series.push({ name: label, color: BLUE, points: daily.map((p, i) => ({ x: i, y: p.algorithm, label: p.date })) });
    const bench = daily.filter((p) => p.benchmark !== undefined);
    if (bench.length >= 2) series.push({ name: `Benchmark (${metrics.benchmark})`, color: GREY, width: 1.5, points: daily.map((p, i) => ({ x: i, y: p.benchmark ?? 0, label: p.date })) });
  } else if (metrics.intraday.length >= 2) {
    series.push({ name: `${label} (intraday valuations)`, color: BLUE, points: metrics.intraday.map((p, i) => ({ x: i, y: p.algorithm, label: p.t.replace("T", " ").slice(0, 16) + "Z" })) });
  }
  return (
    <div>
      <div className="legend" style={{ display: "flex", gap: 16, fontSize: 12, color: "#555b61", marginBottom: 6 }}>
        {series.map((s) => (
          <span key={s.name}>
            <span className="sw" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 5, background: s.color, marginRight: 6, verticalAlign: -1 }} />
            {s.name}
          </span>
        ))}
        {daily.length < 2 ? <span className="muted">benchmark appears after the first completed session</span> : null}
      </div>
      <PerfChart series={series} height={320} emptyText="The curve appears after the second valuation." />
    </div>
  );
}

/** NAV in dollars over every valuation snapshot. */
export function NavCurve({ history }: { history: (TreasurySnapshot | PortfolioSnapshot)[] }) {
  const pts = history.map((h, i) => ({ x: i, y: Number(h.nav), label: h.taken_at.replace("T", " ").slice(0, 16) + "Z" }));
  return <PerfChart series={[{ name: "NAV", color: BLUE, points: pts }]} height={340} format="money" emptyText="NAV history appears after the second valuation." />;
}
