import Link from "next/link";
import type { Status } from "@/lib/types";

export function Footer({ status }: { status: Status | null }) {
  return (
    <footer className="q-foot">
      <div className="inner">
        <div>
          <strong>ZIPLINE</strong> — the open-source Quantopian engine, reconnected to real markets on Robinhood Chain. Independent project; not operated, sponsored or endorsed by Robinhood Markets, Inc. or Quantopian. Not investment advice.
        </div>
        <div>
          <strong>Software</strong>
          <br />
          engine <code>{status?.software.engine ?? "—"}</code> · zipline-reloaded <code>{status?.software.zipline_reloaded ?? "—"}</code> · empyrical-reloaded · exchange-calendars · 0x Swap API v2
        </div>
        <div>
          <strong>Chain</strong>
          <br />
          Robinhood Chain {status?.chain.chain_id ?? "—"} ·{" "}
          <a href={status?.chain.explorer_base_url ?? "https://robinhoodchain.blockscout.com"} target="_blank" rel="noopener noreferrer">
            explorer ↗
          </a>{" "}
          · <Link href="/api/engine/status">engine status (JSON)</Link>
        </div>
      </div>
    </footer>
  );
}
