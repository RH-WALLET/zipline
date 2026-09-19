"use client";

import type { QuoteBoard as Board } from "@/lib/types";
import { fmtInt, fmtPrice, num } from "@/lib/format";

export type Tick = { dir: "up" | "down"; bps: number; at: number };

function clock(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toISOString().slice(11, 19) + "Z";
}

/**
 * The quote board: Robinhood's underlying bid/ask for every tracked Stock Token, the token value
 * (price × ERC-8056 multiplier), and the change since the previous observation. Rows flash when a
 * mid moves. Cached rows (feed down) are dimmed and say so.
 */
export function QuoteBoard({ board, ticks }: { board: Board | null; ticks: Record<string, Tick> }) {
  if (!board) return <div className="book-empty">Quote feed unavailable.</div>;
  return (
    <table className="grid" aria-label="Quote board">
      <thead>
        <tr>
          <th>Token</th>
          <th>Bid</th>
          <th>Ask</th>
          <th>Mid</th>
          <th>Δ bps</th>
          <th className="hide-sm">Spread</th>
          <th className="hide-sm">Token value</th>
          <th>Priced</th>
        </tr>
      </thead>
      <tbody>
        {board.quotes.map((q) => {
          const tick = ticks[q.symbol];
          const cached = q.source !== "robinhood_api";
          const mult = num(q.multiplier) ?? 1;
          return (
            <tr key={`${q.symbol}:${tick?.at ?? 0}`} className={`${cached ? "cached " : ""}${tick ? `tick-${tick.dir}` : ""}`}>
              <td>
                <span className="sym">{q.symbol}</span>
                {q.is_halted ? (
                  <>
                    {" "}
                    <span className="tag bad">halted</span>
                  </>
                ) : null}
                {q.hold_only ? (
                  <>
                    {" "}
                    <span className="tag warn">hold only</span>
                  </>
                ) : null}
                {cached ? (
                  <>
                    {" "}
                    <span className="tag" title={q.error ?? undefined}>
                      {q.source === "cached_snapshot" ? "cached" : "no price"}
                    </span>
                  </>
                ) : null}
              </td>
              <td>{fmtPrice(q.bid)}</td>
              <td>{fmtPrice(q.ask)}</td>
              <td>{fmtPrice(q.mid)}</td>
              <td className={tick ? tick.dir : "faint"}>{tick ? `${tick.dir === "up" ? "▲" : "▼"} ${Math.abs(tick.bps).toFixed(1)}` : "—"}</td>
              <td className="hide-sm dim">{q.spread_bps === null ? "—" : `${Number(q.spread_bps).toFixed(1)} bps`}</td>
              <td className="hide-sm" title={`× ${mult.toFixed(6)} multiplier · daily volume ${q.daily_volume ? fmtInt(q.daily_volume) : "—"}`}>
                {fmtPrice(q.token_mid)}
              </td>
              <td className="dim">{clock(q.generated_at)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
