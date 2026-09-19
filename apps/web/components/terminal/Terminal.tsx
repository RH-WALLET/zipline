"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { Metrics, QuoteBoard as Board, Status, Strategy, SystemEvent, Treasury } from "@/lib/types";
import { fmtInt, num } from "@/lib/format";
import { ago, clockET, clockUTC, countdown, sessionLabel, useClock } from "./clock";
import { BookPane, TreasuryPane } from "./Panes";
import { QuoteBoard, type Tick } from "./QuoteBoard";
import { type Filter, Tape } from "./Tape";

export type TerminalData = {
  status: Status | null;
  treasury: Treasury | null;
  quotes: Board | null;
  events: SystemEvent[];
  metrics: Metrics | null;
  strategies: Strategy[];
};

const TAPE_LIMIT = 400;
const QUOTE_POLL_MS = 20_000;
const STATE_POLL_MS = 60_000;
const SLOW_POLL_MS = 300_000;

async function getJSON<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`/api/engine${path}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

/**
 * The machine's own screen. Everything on it is read from the engine: the tape is the system
 * event log over server-sent events, the board is Robinhood's public quotes polled through the
 * engine, the treasury and books are the accounting endpoints. Nothing is narrated or replayed.
 */
export function Terminal({ initial }: { initial: TerminalData }) {
  const now = useClock();
  const [status, setStatus] = useState(initial.status);
  const [treasury, setTreasury] = useState(initial.treasury);
  const [metrics, setMetrics] = useState(initial.metrics);
  const [strategies, setStrategies] = useState(initial.strategies);
  const [board, setBoard] = useState(initial.quotes);
  const [ticks, setTicks] = useState<Record<string, Tick>>({});
  const [events, setEvents] = useState<SystemEvent[]>(() => [...initial.events].sort((a, b) => a.id - b.id).slice(-TAPE_LIMIT));
  const [filter, setFilter] = useState<Filter>("all");
  const [link, setLink] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const [engineOk, setEngineOk] = useState(initial.status !== null);
  const [lastBeat, setLastBeat] = useState<number>(0);
  // events with an id above this arrived live and get the highlight
  const [freshAfter] = useState(() => (initial.events.length ? Math.max(...initial.events.map((e) => e.id)) : 0));
  const lastId = useRef(freshAfter);
  const prevMids = useRef<Record<string, number>>(Object.fromEntries((initial.quotes?.quotes ?? []).map((q) => [q.symbol, num(q.mid) ?? NaN])));

  // the tape: server-sent events, newest appended at the bottom
  useEffect(() => {
    const es = new EventSource(`/api/stream?after_id=${lastId.current}`);
    es.onopen = () => setLink("live");
    es.onerror = () => setLink("reconnecting");
    es.addEventListener("heartbeat", () => setLastBeat(Date.now()));
    es.addEventListener("system_event", (msg) => {
      try {
        const ev = JSON.parse((msg as MessageEvent).data) as SystemEvent;
        if (ev.id <= lastId.current) return;
        lastId.current = ev.id;
        setLastBeat(Date.now());
        setEvents((prev) => [...prev, ev].slice(-TAPE_LIMIT));
      } catch {
        /* ignore malformed frames */
      }
    });
    return () => es.close();
  }, []);

  // the board: poll on the engine's cache TTL; flash rows whose mid moved
  useEffect(() => {
    const tick = async () => {
      if (document.visibilityState === "hidden") return;
      const next = await getJSON<Board>("/quotes");
      if (!next) return;
      const changes: Record<string, Tick> = {};
      const at = Date.now();
      for (const q of next.quotes) {
        const mid = num(q.mid);
        const prev = prevMids.current[q.symbol];
        if (mid !== null && Number.isFinite(prev) && prev > 0 && mid !== prev) {
          changes[q.symbol] = { dir: mid > prev ? "up" : "down", bps: ((mid - prev) / prev) * 10_000, at };
        }
        if (mid !== null) prevMids.current[q.symbol] = mid;
      }
      setBoard(next);
      if (Object.keys(changes).length) setTicks((t) => ({ ...t, ...changes }));
    };
    const id = setInterval(tick, QUOTE_POLL_MS);
    return () => clearInterval(id);
  }, []);

  // treasury, status, books
  useEffect(() => {
    const fast = async () => {
      if (document.visibilityState === "hidden") return;
      const [s, t] = await Promise.all([getJSON<Status>("/status"), getJSON<Treasury>("/treasury")]);
      setEngineOk(s !== null);
      if (s) setStatus(s);
      if (t) setTreasury(t);
    };
    const slow = async () => {
      if (document.visibilityState === "hidden") return;
      const [m, st] = await Promise.all([getJSON<Metrics>("/treasury/metrics"), getJSON<Strategy[]>("/strategies")]);
      if (m) setMetrics(m);
      if (st) setStrategies(st);
    };
    const a = setInterval(fast, STATE_POLL_MS);
    const b = setInterval(slow, SLOW_POLL_MS);
    return () => {
      clearInterval(a);
      clearInterval(b);
    };
  }, []);

  const mode = status?.mode;
  const paused = mode?.paused ?? false;
  const liveTrading = mode?.live_trading ?? false;
  const stamp = !status
    ? { cls: "paused", text: "engine unreachable", sub: "nothing here is cached or invented" }
    : paused
      ? { cls: "paused", text: "system paused", sub: mode?.pause_reason ?? "operator" }
      : liveTrading
        ? { cls: "live", text: "live trading", sub: `onchain · robinhood chain ${status.chain.chain_id}` }
        : { cls: "", text: "demo mode", sub: "live trading disabled · dry run" };
  const lastCycle = status?.system.last_cycle ?? null;
  const beatAge = lastBeat && now ? (now - lastBeat) / 1000 : null;
  const streamDot = link === "live" ? (beatAge !== null && beatAge > 45 ? "warn" : "") : link === "connecting" ? "warn" : "bad";

  return (
    <>
      <header className="term-bar">
        <div className="term-brand">
          <b>ZIPLINE</b>
          <span>
            terminal<i className="cursor" aria-hidden="true" />
          </span>
        </div>
        <div className={`term-stamp ${stamp.cls}`} role="status">
          {stamp.text}
          <small>{stamp.sub}</small>
        </div>
        <div className="k">
          <span className={`dot ${!engineOk ? "bad" : paused ? "warn" : ""}`} aria-hidden="true" />
          {!engineOk ? "engine offline" : paused ? "engine paused" : "engine online"} · chain <b>{status?.chain.chain_id ?? "—"}</b>
        </div>
        <div className="spacer" />
        <div className="term-clock k">
          UTC <b>{clockUTC(now)}</b> · ET <b>{clockET(now)}</b>
        </div>
        <div className="k">
          <span className={`dot ${status?.system.market?.is_open ? "" : "warn"}`} aria-hidden="true" />
          NYSE <b>{sessionLabel(status?.system.market)}</b>
        </div>
        <div className="k" title={`daily cycle at ${status?.system.cycle_time_et ?? "16:20"} ET, after the close`}>
          cycle <b>{countdown(status?.system.next_cycle_at, now)}</b>
        </div>
        <Link href="/" className="back">
          ← report
        </Link>
      </header>

      <div className="term-main">
        <section className="pane tape" aria-label="Tape">
          <div className="pane-head">
            <span>
              tape
              <span className="filters" role="group" aria-label="Tape filter">
                {(["all", "trades", "signals", "system"] as Filter[]).map((f) => (
                  <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                    {f}
                  </button>
                ))}
              </span>
            </span>
            <span className="meta">
              <span className={`dot ${streamDot}`} aria-hidden="true" />
              <b>{link}</b> · {fmtInt(events.length)} lines · last event <b>{events.length ? ago(events[events.length - 1].created_at, now) : "—"}</b>
            </span>
          </div>
          <Tape events={events} filter={filter} freshAfter={freshAfter} />
        </section>

        <div className="term-col">
          <section className="pane treasury" aria-label="Treasury">
            <div className="pane-head">
              <span>treasury</span>
              <span className="meta">
                {treasury?.snapshot?.mode ?? "—"} · <b>{Object.keys(treasury?.holdings ?? {}).length}</b> tokens held · <b>{status?.counts.executions ?? 0}</b> executions · <b>{status?.counts.real_transactions ?? 0}</b> onchain
              </span>
            </div>
            <TreasuryPane treasury={treasury} metrics={metrics} now={now} />
          </section>

          <section className="pane quotes" aria-label="Quote board">
            <div className="pane-head">
              <span>quote board</span>
              <span className="meta" title={board?.source}>
                robinhood · <b>{board?.live ?? 0}</b> live{board && board.cached ? ` · ${board.cached} cached` : ""} · refreshed <b>{ago(board?.fetched_at, now)}</b>
              </span>
            </div>
            <div className="pane-body">
              <QuoteBoard board={board} ticks={ticks} />
            </div>
          </section>

          <section className="pane book" aria-label="Books">
            <div className="pane-head">
              <span>books</span>
              <span className="meta">
                <b>{strategies.filter((s) => s.status === "ACTIVE").length}</b> / {strategies.length} sleeves active
              </span>
            </div>
            <div className="pane-body">
              <BookPane treasury={treasury} strategies={strategies} />
            </div>
          </section>
        </div>
      </div>

      <footer className="term-foot">
        <span>
          last cycle <b>{lastCycle ? `#${lastCycle.id}` : "—"}</b>
          {lastCycle ? (
            <>
              {" "}
              · session {lastCycle.session_date} · {lastCycle.mode} · {String(lastCycle.summary?.signals ?? "—")} signals · {String(lastCycle.summary?.net_orders ?? "—")} net orders · {String(lastCycle.summary?.internal_crosses ?? "—")} crosses
            </>
          ) : null}{" "}
          · reconciliation <b>{status?.system.last_reconciliation_status?.replace("RECONCILIATION_", "") ?? "—"}</b> {ago(status?.system.last_reconciliation_at, now)}
        </span>
        <span>{liveTrading ? "onchain orders carry a Robinhood Chain transaction hash" : "dry-run fills carry local ids (dry-000042); no chain transactions"} · nothing narrated, nothing replayed</span>
      </footer>
    </>
  );
}
