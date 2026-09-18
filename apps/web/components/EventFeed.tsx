"use client";

import { useEffect, useRef, useState } from "react";
import type { SystemEvent } from "@/lib/types";
import { fmtTime } from "@/lib/format";

/** The dark log console Quantopian backtests had, fed live over SSE with the engine's own events. */
export function EventFeed({ initial, limit = 60, height = 420 }: { initial: SystemEvent[]; limit?: number; height?: number | string }) {
  const [events, setEvents] = useState<SystemEvent[]>(initial);
  const [connected, setConnected] = useState<boolean>(false);
  const lastId = useRef<number>(initial.length ? Math.max(...initial.map((e) => e.id)) : 0);

  useEffect(() => {
    const es = new EventSource(`/api/stream?after_id=${lastId.current}`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("system_event", (msg) => {
      try {
        const ev = JSON.parse((msg as MessageEvent).data) as SystemEvent;
        if (ev.id <= lastId.current) return;
        lastId.current = ev.id;
        setEvents((prev) => [ev, ...prev].slice(0, limit));
      } catch {
        /* ignore malformed frames */
      }
    });
    return () => es.close();
  }, [limit]);

  return (
    <div className="console" aria-label="System log">
      <div className="bar">
        <span>
          <span className={`live ${connected ? "" : "off"}`}>●</span> {connected ? "live" : "reconnecting"} · engine event log · newest first
        </span>
        <span>{events.length} lines</span>
      </div>
      <div className="lines" style={{ maxHeight: height }}>
        {events.length === 0 ? <span className="ln ts">No events yet.</span> : null}
        {events.map((e) => (
          <span key={e.id} className={`ln ${e.level === "WARN" ? "warn" : e.level === "ERROR" ? "error" : ""}`}>
            <span className="ts">{fmtTime(e.created_at)}</span>
            {"  "}
            <span className={`ty ${e.level === "WARN" ? "warn" : e.level === "ERROR" ? "error" : ""}`}>{e.type.padEnd(26)}</span>
            {" "}
            <span className="msg">{e.message}</span>
            {"\n"}
          </span>
        ))}
      </div>
    </div>
  );
}
