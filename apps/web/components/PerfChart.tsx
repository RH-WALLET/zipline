"use client";

import { useMemo, useRef, useState } from "react";

export type Series = { name: string; color: string; points: { x: number; y: number; label: string }[]; width?: number };

/**
 * Cumulative-performance chart in the shape Quantopian used: percent on the right axis,
 * dotted horizontal grid, algorithm in blue, benchmark in grey, crosshair tooltip on hover.
 */
export function PerfChart({ series, height = 300, unit = "%", format = "pct", emptyText = "Not enough valuations yet." }: { series: Series[]; height?: number; unit?: string; format?: "pct" | "money"; emptyText?: string }) {
  const W = 1000;
  const H = height;
  const padL = 12;
  const padR = format === "money" ? 96 : 64;
  const padT = 16;
  const padB = 32;
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const live = series.filter((s) => s.points.length >= 2);
  const model = useMemo(() => {
    if (!live.length) return null;
    const xs = live.flatMap((s) => s.points.map((p) => p.x));
    const ys = live.flatMap((s) => s.points.map((p) => p.y));
    const x0 = Math.min(...xs);
    let x1 = Math.max(...xs);
    if (x1 === x0) x1 = x0 + 1;
    let y0 = Math.min(0, ...ys);
    let y1 = Math.max(0, ...ys);
    const span = Math.max(y1 - y0, 0.05);
    y0 -= span * 0.12;
    y1 += span * 0.12;
    const sx = (x: number) => padL + ((x - x0) / (x1 - x0)) * (W - padL - padR);
    const sy = (y: number) => padT + (1 - (y - y0) / (y1 - y0)) * (H - padT - padB);
    const step = niceStep((y1 - y0) / 5);
    const ticks: number[] = [];
    for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) ticks.push(Number(v.toFixed(8)));
    const primary = live[0].points;
    const longLabels = primary.some((p) => p.label.length > 10);
    const fractions = longLabels ? [0, 0.5, 1] : [0, 0.25, 0.5, 0.75, 1];
    const xTicks = fractions.map((f) => primary[Math.min(primary.length - 1, Math.round(f * (primary.length - 1)))]);
    return { x0, x1, y0, y1, sx, sy, ticks, xTicks, primary };
  }, [live, H, padR]);

  if (!model) return <div className="empty">{emptyText}</div>;
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
  const tipLeft = hp ? (sx(hp.x) / W) * 100 : 0;
  const tipTop = hp ? (sy(hp.y) / H) * 100 : 0;
  const fmt =
    format === "money"
      ? (v: number) => `$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
      : (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}${unit}`;

  return (
    <div className="chart" ref={wrap}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="cumulative performance" onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke={Math.abs(t) < 1e-9 ? "#b8bec4" : "#e6e8eb"} strokeWidth={Math.abs(t) < 1e-9 ? 1 : 1} strokeDasharray={Math.abs(t) < 1e-9 ? undefined : "2 4"} />
            <text x={W - padR + 10} y={sy(t) + 4} fontSize="11" fill="#8a9096" fontFamily="inherit" style={{ fontVariantNumeric: "tabular-nums" }}>
              {fmt(t)}
            </text>
          </g>
        ))}
        {xTicks.map((p, i) => (
          <text key={i} x={sx(p.x)} y={H - 10} fontSize="11" fill="#8a9096" textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}>
            {p.label}
          </text>
        ))}
        {live.map((s) => (
          <path key={s.name} d={s.points.map((p, i) => `${i ? "L" : "M"}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ")} fill="none" stroke={s.color} strokeWidth={s.width ?? 2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {hp ? (
          <g>
            <line x1={sx(hp.x)} x2={sx(hp.x)} y1={padT} y2={H - padB} stroke="#b8bec4" strokeDasharray="3 3" />
            {live.map((s) => {
              const q = s.points[Math.min(hover!, s.points.length - 1)];
              return q ? <circle key={s.name} cx={sx(q.x)} cy={sy(q.y)} r="3.5" fill="#fff" stroke={s.color} strokeWidth="2" /> : null;
            })}
          </g>
        ) : null}
      </svg>
      {hp ? (
        <div className="tip" style={{ left: `${tipLeft}%`, top: `calc(${tipTop}% - 12px)` }}>
          <div className="t">{hp.label}</div>
          {live.map((s) => {
            const q = s.points[Math.min(hover!, s.points.length - 1)];
            return q ? (
              <div key={s.name}>
                <span className="sw" style={{ background: s.color, display: "inline-block", width: 8, height: 8, borderRadius: 4, marginRight: 6 }} />
                {s.name}: <strong className="tnum">{fmt(q.y)}</strong>
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
