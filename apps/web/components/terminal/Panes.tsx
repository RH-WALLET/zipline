"use client";

import type { Metrics, Strategy, Treasury } from "@/lib/types";
import { fmtEth, fmtInt, fmtMoney, fmtPct, fmtQty, num, twrToReturnPct } from "@/lib/format";
import { ago } from "./clock";

/** Sparkline of the treasury's intraday time-weighted return: no axes, a zero line, the last point marked. */
function Spark({ points }: { points: number[] }) {
  if (points.length < 2) return <div className="faint" style={{ fontSize: 11 }}>sparkline appears after the second valuation</div>;
  const W = 400;
  const H = 46;
  const min = Math.min(0, ...points);
  const max = Math.max(0, ...points);
  const span = max - min || 1;
  const sx = (i: number) => (i / (points.length - 1)) * (W - 6) + 3;
  const sy = (v: number) => 4 + (1 - (v - min) / span) * (H - 8);
  const d = points.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  const color = last >= 0 ? "var(--green)" : "var(--red)";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Intraday time-weighted return">
      <line x1={0} x2={W} y1={sy(0)} y2={sy(0)} stroke="var(--tr2)" strokeWidth="1" />
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={sx(points.length - 1)} cy={sy(last)} r="2.5" fill={color} />
    </svg>
  );
}

export function TreasuryPane({ treasury, metrics, now }: { treasury: Treasury | null; metrics: Metrics | null; now: number }) {
  const snap = treasury?.snapshot ?? null;
  if (!snap) return <div className="book-empty">No valuation yet.</div>;
  const ret = twrToReturnPct(snap.twr_index);
  const r = num(ret) ?? 0;
  const positions = Object.keys(snap.positions ?? {}).length;
  return (
    <div className="tre">
      <div>
        <div className="label">net asset value · {treasury?.cash_token.symbol ?? "USDG"}</div>
        <div className="nav">{fmtMoney(snap.nav)}</div>
      </div>
      <div>
        <div className="label">time-weighted</div>
        <div className={`ret ${r > 0 ? "pos" : r < 0 ? "neg" : "dim"}`}>{fmtPct(ret)}</div>
      </div>
      <div className="spark">
        <Spark points={(metrics?.intraday ?? []).map((p) => p.algorithm)} />
      </div>
      <div className="facts">
        <div>
          <span className="label">cash</span>
          {fmtMoney(snap.cash_balance)}
        </div>
        <div>
          <span className="label">stock tokens</span>
          {fmtMoney(snap.positions_value)} <span className="faint">· {positions}</span>
        </div>
        <div>
          <span className="label">reserve</span>
          {fmtMoney(snap.reserved_cash)}
        </div>
        <div>
          <span className="label">gas</span>
          {fmtEth(snap.gas_balance_eth, 4)}
        </div>
        <div>
          <span className="label">unrealized</span>
          <span className={num(snap.unrealized_pnl)! > 0 ? "pos" : num(snap.unrealized_pnl)! < 0 ? "neg" : ""}>{fmtMoney(snap.unrealized_pnl, { sign: true })}</span>
        </div>
        <div>
          <span className="label">valued</span>
          {ago(snap.taken_at, now)}
        </div>
      </div>
    </div>
  );
}

export function BookPane({ treasury, strategies }: { treasury: Treasury | null; strategies: Strategy[] }) {
  const holdings = Object.entries(treasury?.holdings ?? {}).sort((a, b) => Number(b[1].market_value) - Number(a[1].market_value));
  const nav = num(treasury?.snapshot?.nav) ?? 0;
  return (
    <>
      <div className="book-sub">positions · Σ sleeve books · raw token units</div>
      {holdings.length === 0 ? (
        <div className="book-empty">All cash.</div>
      ) : (
        <table className="grid" aria-label="Positions">
          <thead>
            <tr>
              <th>Token</th>
              <th>Quantity</th>
              <th>Value</th>
              <th>Weight</th>
              <th>Unrealized</th>
            </tr>
          </thead>
          <tbody>
            {holdings.map(([sym, h]) => {
              const u = num(h.unrealized_pnl) ?? 0;
              return (
                <tr key={sym}>
                  <td>
                    <span className="sym">{sym}</span>
                  </td>
                  <td>{fmtQty(h.quantity)}</td>
                  <td>{fmtMoney(h.market_value)}</td>
                  <td className="dim">{nav > 0 ? `${((Number(h.market_value) / nav) * 100).toFixed(1)}%` : "—"}</td>
                  <td className={u > 0 ? "pos" : u < 0 ? "neg" : "dim"}>{fmtMoney(h.unrealized_pnl, { sign: true })}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="book-sub">sleeves · {strategies.length} strategies</div>
      {strategies.length === 0 ? (
        <div className="book-empty">No strategies.</div>
      ) : (
        <table className="grid" aria-label="Sleeves">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Return</th>
              <th>Virtual NAV</th>
              <th className="hide-sm">Cash</th>
              <th className="hide-sm">Signals / fills</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((s) => {
              const ret = twrToReturnPct(s.state?.twr_index);
              const r = num(ret) ?? 0;
              return (
                <tr key={s.code}>
                  <td>
                    <span className="sym">{s.code}</span> <span className="faint">{s.name}</span>
                  </td>
                  <td className={r > 0 ? "pos" : r < 0 ? "neg" : "dim"}>{fmtPct(ret)}</td>
                  <td>{fmtMoney(s.state?.current_nav)}</td>
                  <td className="hide-sm dim">{fmtMoney(s.state?.virtual_cash)}</td>
                  <td className="hide-sm dim">
                    {fmtInt(s.state?.signals_count)} / {fmtInt(s.state?.fills_count)}
                  </td>
                  <td>
                    <span className={`tag ${s.status === "ACTIVE" ? "ok" : s.status === "WATCH" ? "warn" : "bad"}`}>{s.status}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}
