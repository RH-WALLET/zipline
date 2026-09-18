import Link from "next/link";
import type { Status } from "@/lib/types";

/** Full-width mode statement under the navbar. Amber while live trading is off; never absent. */
export function ModeBar({ status }: { status: Status | null }) {
  if (!status) {
    return (
      <div className="mode-bar paused" role="alert">
        <div className="inner">
          <strong>ENGINE UNREACHABLE</strong>
          <span>Nothing on this page is cached or invented while the engine is down.</span>
        </div>
      </div>
    );
  }
  if (status.mode.paused) {
    return (
      <div className="mode-bar paused" role="alert">
        <div className="inner">
          <strong>SYSTEM PAUSED</strong>
          <span>{status.mode.pause_reason ?? "operator"} · no cycles run and no orders are sent while paused</span>
        </div>
      </div>
    );
  }
  if (status.mode.live_trading) {
    return (
      <div className="mode-bar live" role="status">
        <div className="inner">
          <strong>LIVE TRADING</strong>
          <span>onchain execution through 0x on Robinhood Chain {status.chain.chain_id} · every confirmed order links to its transaction</span>
        </div>
      </div>
    );
  }
  return (
    <div className="mode-bar" role="status">
      <div className="inner">
        <strong>DEMO MODE — LIVE TRADING DISABLED</strong>
        <span>
          {status.mode.treasury_mode === "simulated" ? "simulated treasury" : "read-only onchain treasury"} · dry-run execution at Robinhood bid/ask × multiplier · local ids (<code>dry-000042</code>), no transaction hashes · not blockchain activity ·{" "}
          <Link href="/methodology#modes">what live requires</Link>
        </span>
      </div>
    </div>
  );
}
