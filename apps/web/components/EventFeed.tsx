"use client";

import { useEffect, useRef, useState } from "react";
import type { SystemEvent } from "@/lib/types";
import { fmtTime } from "@/lib/format";

/** The system log as a printed appendix, fed live over SSE with the engine's own events. */
export function EventFeed({ initial, limit = 60, height = 420 }: { initial: SystemEvent[]; limit?: number; height?: number | string }) {
  const [events, setEvents] = useState<SystemEvent[]>(initial);
  const [link, setLink] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const lastId = useRef<number>(initial.length ? Math.max(...initial.map((e) => e.id)) : 0);

  useEffect(() => {
    const es = new EventSource(`/api/stream?after_id=${lastId.current}`);
    es.onopen = () => setLink("live");
    es.onerror = () => setLink("reconnecting");
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
    <div className="log" aria-label="System log">
      <div className="bar">
        <span>
          <span className={link === "live" ? "pos" : link === "connecting" ? "muted" : "warn"}>●</span> {link} · engine event log · newest first
        </span>
        <span>{events.length} lines</span>
      </div>
      <div className="lines" style={{ maxHeight: height }}>
        {events.length === 0 ? <span className="ts">No events yet.</span> : null}
        {events.map((e) => {
          const level = e.level === "WARN" ? "warn" : e.level === "ERROR" ? "error" : "";
          return (
            <div key={e.id} className={`ln ${level}`}>
              <span className="ts">{fmtTime(e.created_at)}</span>
              <span className={`ty ${level}`}>{e.type}</span>
              <span className="msg">{e.message}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
