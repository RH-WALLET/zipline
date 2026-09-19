import type { Status } from "@/lib/types";

/** The document stamp: the report's mode, impossible to miss and impossible to mistake. */
export function Stamp({ status }: { status: Status | null }) {
  if (!status) {
    return (
      <div className="stamp paused" role="alert">
        Engine unreachable<small>nothing here is cached or invented</small>
      </div>
    );
  }
  if (status.mode.paused) {
    return (
      <div className="stamp paused" role="alert">
        System paused<small>{status.mode.pause_reason ?? "operator"}</small>
      </div>
    );
  }
  if (status.mode.live_trading) {
    return (
      <div className="stamp live" role="status">
        Live trading<small>onchain · Robinhood Chain {status.chain.chain_id}</small>
      </div>
    );
  }
  return (
    <div className="stamp" role="status">
      Demo mode<small>live trading disabled · dry run</small>
    </div>
  );
}
