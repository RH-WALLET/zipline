"use client";

import { useEffect, useRef, useState } from "react";
import type { SystemEvent } from "@/lib/types";

export type Category = "exec" | "dry" | "cross" | "signal" | "risk" | "recon" | "treasury" | "data" | "system";
export type Filter = "all" | "trades" | "signals" | "system";

/** Every event type the engine emits, sorted into the colour it prints in. */
export function categorize(type: string): Category {
  if (type === "EXECUTION_DRY_RUN") return "dry";
  if (type.startsWith("EXECUTION_") || type === "QUOTE_RECEIVED") return "exec";
  if (type === "INTERNAL_CROSS") return "cross";
  if (type.startsWith("STRATEGY_SIGNAL") || type === "TARGETS_AGGREGATED") return "signal";
  if (type === "RISK_LIMIT_APPLIED" || type === "ORDER_REJECTED" || type === "QUOTE_REJECTED") return "risk";
  if (type.startsWith("RECONCILIATION")) return "recon";
  if (type === "TREASURY_UPDATED" || type === "FUNDING_RECEIVED" || type === "WITHDRAWAL_RECORDED") return "treasury";
  if (type === "MARKET_DATA_UPDATED" || type === "UNIVERSE_UPDATED" || type === "ASSET_REMOVED") return "data";
  return "system";
}

const FILTERS: Record<Filter, Category[] | null> = {
  all: null,
  trades: ["exec", "dry", "cross"],
  signals: ["signal", "risk"],
  system: ["system", "recon", "treasury", "data"],
};

export function matches(filter: Filter, type: string): boolean {
  const cats = FILTERS[filter];
  return cats === null || cats.includes(categorize(type));
}

function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toISOString().slice(11, 19) + "Z";
}

/**
 * The tape: the engine's events, oldest at the top, newest at the bottom, auto-following like a
 * tail unless the reader has scrolled up to look at something.
 */
export function Tape({ events, filter, freshAfter }: { events: SystemEvent[]; filter: Filter; freshAfter: number }) {
  const body = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const visible = events.filter((e) => matches(filter, e.type));
  const lastId = visible.length ? visible[visible.length - 1].id : 0;

  useEffect(() => {
    const el = body.current;
    if (el && following) el.scrollTop = el.scrollHeight;
  }, [lastId, filter, following]);

  const onScroll = () => {
    const el = body.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (atBottom !== following) setFollowing(atBottom);
  };

  return (
    <div className="pane-body" ref={body} onScroll={onScroll} role="log" aria-label="Event tape">
      <div className="tape-lines">
        {visible.length === 0 ? <div className="tape-empty">No events of this kind yet.</div> : null}
        {visible.map((e) => (
          <div key={e.id} className={`tl c-${categorize(e.type)} l-${e.level.toLowerCase()}${e.id > freshAfter ? " fresh" : ""}`}>
            <span className="t">{clock(e.created_at)}</span>
            <span className="ty" title={e.type}>
              {e.type}
            </span>
            <span className="m">{e.message}</span>
          </div>
        ))}
      </div>
      {!following ? (
        <button
          type="button"
          className="tape-jump"
          onClick={() => {
            setFollowing(true);
            const el = body.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
        >
          ↓ follow
        </button>
      ) : null}
    </div>
  );
}
