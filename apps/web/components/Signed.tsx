import { fmtMoney, fmtPct, signClass } from "@/lib/format";

export function Money({ v, sign = false }: { v: string | number | null | undefined; sign?: boolean }) {
  return <span className={sign ? signClass(v) : ""}>{fmtMoney(v, { sign })}</span>;
}

export function Pct({ v, digits = 2 }: { v: string | number | null | undefined; digits?: number }) {
  return <span className={signClass(v)}>{fmtPct(v, digits)}</span>;
}
