"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type Series = { name: string; color: string; points: { x: number; y: number; label: string }[]; width?: number; fill?: boolean };

const font = "var(--font-mono)";

/**
 * Tear-sheet plot: no frame, faint horizontal grid, a solid zero line, monospaced tick labels,
 * hairline series, crosshair tooltip on hover. Used for cumulative returns, drawdowns and NAV.
 */
export function PerfChart({ series, height = 280, unit = "%", format = "pct", emptyText = "Not enough valuations yet.", baseline = true }: { series: Series[]; height?: number; unit?: string; format?: "pct" | "money" | "plain"; emptyText?: string; baseline?: boolean }) {
  // The viewBox tracks the rendered width so tick labels stay at a true 11px instead of
  // shrinking with the SVG. 640 is the server-side guess; ResizeObserver corrects it on mount.
  const wrap = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(640);
  useEffect(() => {
    const el = wrap.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setW(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const H = height;
  const padL = 8;
  const padR = format === "money" ? 92 : 62;
  const padT = 10;
  const padB = 30;
  const [hover, setHover] = useState<number | null>(null);

  const live = series.filter((s) => s.points.length >= 2);
  const model = useMemo(() => {
    if (!live.length) return null;
    const xs = live.flatMap((s) => s.points.map((p) => p.x));
    const ys = live.flatMap((s) => s.points.map((p) => p.y));
    const x0 = Math.min(...xs);
    let x1 = Math.max(...xs);
    if (x1 === x0) x1 = x0 + 1;
    let y0 = baseline ? Math.min(0, ...ys) : Math.min(...ys);
    let y1 = baseline ? Math.max(0, ...ys) : Math.max(...ys);
    const span = Math.max(y1 - y0, 0.05);
    y0 -= span * 0.1;
    y1 += span * 0.1;
    const sx = (x: number) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR);
    const sy = (y: number) => padT + (1 - (y - y0) / (y1 - y0)) * (H - padT - padB);
    const step = niceStep((y1 - y0) / 5);
    const ticks: number[] = [];
    for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) ticks.push(Number(v.toFixed(8)));
    const primary = live[0].points;
    const longLabels = primary.some((p) => p.label.length > 10);
    const slots = Math.max(2, Math.min(longLabels ? 4 : 6, Math.floor((W - padL - padR) / (longLabels ? 190 : 110)) + 1));
    const fractions = Array.from({ length: slots }, (_, i) => i / (slots - 1));
    const xTicks = fractions.map((f) => primary[Math.min(primary.length - 1, Math.round(f * (primary.length - 1)))]);
    return { sx, sy, ticks, xTicks, primary };
  }, [live, W, H, padR, baseline]);

  if (!model)
    return (
      <div className="chart" ref={wrap}>
        <div className="empty">{emptyText}</div>
      </div>
    );
  const { sx, sy, ticks, xTicks, primary } = model;

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestD = Infinity;
    primary.forEach((p, i) => {
      const d = Math.abs(sx(p.x) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setHover(best);
  };
  const hp = hover !== null ? primary[hover] : null;
  const fmt =
    format === "money"
      ? (v: number) => `$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : format === "plain"
        ? (v: number) => `${v.toFixed(2)}`
        : (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}${unit}`;

  return (
    <div className="chart" ref={wrap}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="plot" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke={Math.abs(t) < 1e-9 ? "#9a9a9a" : "#e6e2d9"} strokeWidth="1" />
            <text x={W - padR + 10} y={sy(t) + 4} fontSize="11" fill="#6b6f76" fontFamily={font} style={{ fontVariantNumeric: "tabular-nums" }}>
              {fmt(t)}
            </text>
          </g>
        ))}
        {xTicks.map((p, i) => (
          <text key={i} x={sx(p.x)} y={H - 8} fontSize="11" fill="#6b6f76" fontFamily={font} textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}>
            {p.label}
          </text>
        ))}
        {live.map((s) =>
          s.fill ? (
            <path key={`${s.name}-fill`} d={`${s.points.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ")} L${sx(s.points[s.points.length - 1].x).toFixed(1)},${sy(0).toFixed(1)} L${sx(s.points[0].x).toFixed(1)},${sy(0).toFixed(1)} Z`} fill={s.color} fillOpacity="0.14" stroke="none" />
          ) : null,
        )}
        {live.map((s) => (
          <path key={s.name} d={s.points.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ")} fill="none" stroke={s.color} strokeWidth={s.width ?? 1.6} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {hp ? (
          <g>
            <line x1={sx(hp.x)} x2={sx(hp.x)} y1={padT} y2={H - padB} stroke="#c9c4b9" strokeDasharray="3 3" />
            {live.map((s) => {
              const q = s.points[Math.min(hover!, s.points.length - 1)];
              return q ? <circle key={s.name} cx={sx(q.x)} cy={sy(q.y)} r="3" fill="#faf9f6" stroke={s.color} strokeWidth="1.5" /> : null;
            })}
          </g>
        ) : null}
        <line x1={padL} x2={W - padR} y1={H - padB} y2={H - padB} stroke="#c9c4b9" />
      </svg>
      {hp ? (
        <div className="tip" style={{ left: `${(sx(hp.x) / W) * 100}%`, top: `calc(${(sy(hp.y) / H) * 100}% - 12px)` }}>
          <div className="t">{hp.label}</div>
          {live.map((s) => {
            const q = s.points[Math.min(hover!, s.points.length - 1)];
            return q ? (
              <div key={s.name}>
                <span style={{ display: "inline-block", width: 10, height: 2, background: s.color, marginRight: 6, verticalAlign: "middle" }} />
                {s.name} {fmt(q.y)}
              </div>
            ) : null;
          })}
        </div>
      ) : null}
    </div>
  );
}

function niceStep(rough: number): number {
  if (!(rough > 0)) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const n = rough / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}
