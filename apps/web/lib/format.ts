/** Formatting helpers. Inputs are decimal strings from the API; never rounded before display. */

export function num(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

const money0 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function fmtMoney(v: string | number | null | undefined, opts: { sign?: boolean; dash?: string } = {}): string {
  const n = num(v);
  if (n === null) return opts.dash ?? "—";
  const s = money0.format(Math.abs(n));
  if (opts.sign) return n < 0 ? `−$${s}` : n > 0 ? `+$${s}` : `$${s}`;
  return n < 0 ? `−$${s}` : `$${s}`;
}

export function fmtPct(v: string | number | null | undefined, digits = 2, sign = true): string {
  const n = num(v);
  if (n === null) return "—";
  const s = Math.abs(n).toFixed(digits) + "%";
  if (!sign) return (n < 0 ? "−" : "") + s;
  return n < 0 ? `−${s}` : n > 0 ? `+${s}` : s;
}

export function fmtWeight(v: string | number | null | undefined, digits = 1): string {
  const n = num(v);
  if (n === null) return "—";
  return (n * 100).toFixed(digits) + "%";
}

export function fmtQty(v: string | number | null | undefined, digits = 6): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPrice(v: string | number | null | undefined): string {
  const n = num(v);
  if (n === null) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

export function fmtBps(v: string | number | null | undefined): string {
  const n = num(v);
  if (n === null) return "—";
  return `${n >= 0 ? "" : "−"}${Math.abs(n).toFixed(1)} bps`;
}

export function fmtEth(v: string | number | null | undefined, digits = 6): string {
  const n = num(v);
  if (n === null) return "—";
  return `${n.toFixed(digits)} ETH`;
}

export function fmtInt(v: number | string | null | undefined): string {
  const n = num(v);
  return n === null ? "—" : Math.round(n).toLocaleString("en-US");
}

export function shortHash(h: string | null | undefined, head = 10, tail = 6): string {
  if (!h) return "—";
  if (h.length <= head + tail + 1) return h;
  return `${h.slice(0, head)}…${h.slice(-tail)}`;
}

export function shortAddr(a: string | null | undefined): string {
  return shortHash(a, 6, 4);
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().replace("T", " ").slice(0, 19) + "Z";
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toISOString().slice(11, 19);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export function fmtAge(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function fmtUntil(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.round((t - now) / 1000);
  if (s <= 0) return "due";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h >= 24) return `in ${Math.floor(h / 24)}d ${h % 24}h`;
  return h > 0 ? `in ${h}h ${m}m` : `in ${m}m`;
}

export function signClass(v: string | number | null | undefined): string {
  const n = num(v);
  if (n === null || n === 0) return "";
  return n > 0 ? "pos" : "neg";
}

export function statusClass(status: string | null | undefined): string {
  switch ((status ?? "").toUpperCase()) {
    case "ACTIVE":
    case "CONFIRMED":
    case "COMPLETED":
    case "RECONCILIATION_OK":
    case "OK":
    case "ONLINE":
      return "green";
    case "WATCH":
    case "DRY_RUN_FILLED":
    case "DRY_RUN":
    case "SIMULATED":
    case "PENDING":
    case "RUNNING":
    case "STALE":
      return "amber";
    case "DISABLED":
    case "FAILED":
    case "REJECTED":
    case "REVERTED":
    case "RECONCILIATION_FAILED":
    case "PAUSED":
    case "DROPPED":
      return "red";
    default:
      return "";
  }
}

export function explorerTx(base: string, hash: string): string {
  return `${base.replace(/\/$/, "")}/tx/${hash}`;
}

export function explorerAddress(base: string, addr: string): string {
  return `${base.replace(/\/$/, "")}/address/${addr}`;
}

export function isLocalId(id: string): boolean {
  return /^dry-\d+$/.test(id);
}

export function twrToReturnPct(twr: string | number | null | undefined): number | null {
  const n = num(twr);
  return n === null ? null : (n - 1) * 100;
}
