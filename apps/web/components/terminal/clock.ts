"use client";

import { useSyncExternalStore } from "react";

/** A one-second clock as an external store, so render stays pure and the lint rules stay quiet. */
let current = 0;
let timer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function subscribe(cb: () => void) {
  listeners.add(cb);
  if (timer === null) {
    current = Date.now();
    timer = setInterval(() => {
      current = Date.now();
      listeners.forEach((l) => l());
    }, 1000);
  }
  return () => {
    listeners.delete(cb);
    if (listeners.size === 0 && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };
}

/** Milliseconds since epoch, ticking once a second; 0 on the server and before the first tick. */
export function useClock(): number {
  return useSyncExternalStore(
    subscribe,
    () => current,
    () => 0,
  );
}

const utc = new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
const et = new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function clockUTC(ms: number): string {
  return ms ? utc.format(new Date(ms)) : "--:--:--";
}
export function clockET(ms: number): string {
  return ms ? et.format(new Date(ms)) : "--:--:--";
}

/** "2d 07:54:12" until an ISO instant; "due" once it has passed. */
export function countdown(iso: string | null | undefined, now: number): string {
  if (!iso || !now) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  let s = Math.round((t - now) / 1000);
  if (s <= 0) return "due now";
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const hms = `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `in ${d > 0 ? `${d}d ${hms}` : hms}`;
}

/** "9h 45m ago" from an ISO instant. */
export function ago(iso: string | null | undefined, now: number): string {
  if (!iso || !now) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h ago`;
}

const etDay = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false });

/** "opens Mon 09:30 ET" / "closes 16:00 ET" for the status bar. */
export function sessionLabel(market: { is_open: boolean; next_open: string; next_close: string } | undefined | null): string {
  if (!market) return "—";
  const when = new Date(market.is_open ? market.next_close : market.next_open);
  if (Number.isNaN(when.getTime())) return market.is_open ? "open" : "closed";
  const parts = etDay.formatToParts(when);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const hm = `${get("hour")}:${get("minute")}`;
  return market.is_open ? `open · closes ${hm} ET` : `closed · ${get("weekday")} ${hm} ET`;
}
