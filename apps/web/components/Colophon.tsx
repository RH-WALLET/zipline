import Link from "next/link";
import type { Status } from "@/lib/types";

export function Colophon({ status }: { status: Status | null }) {
  return (
    <footer className="colophon">
      <div className="inner">
        <div>
          <b>ZIPLINE</b> — the open-source Quantopian engine, reconnected to real markets on Robinhood Chain. Independent project; not operated, sponsored or endorsed by Robinhood Markets, Inc. or Quantopian. Not investment advice.
        </div>
        <div>
          <b>Set live by</b> zipline-engine {status?.software.engine ?? "—"} · zipline-reloaded {status?.software.zipline_reloaded ?? "—"} · empyrical-reloaded · exchange-calendars · 0x Swap API v2.
          <br />
          Statistics follow pyfolio&apos;s <code>perf_stats</code>; returns are time-weighted; the benchmark is SPY.
        </div>
        <div>
          <b>Chain</b> Robinhood Chain {status?.chain.chain_id ?? "—"} ·{" "}
          <a href={status?.chain.explorer_base_url ?? "https://robinhoodchain.blockscout.com"} target="_blank" rel="noopener noreferrer">
            explorer ↗
          </a>{" "}
          · <Link href="/api/engine/status">engine status (JSON)</Link> · <a href="https://github.com/RH-WALLET/zipline">source ↗</a>
        </div>
      </div>
    </footer>
  );
}
