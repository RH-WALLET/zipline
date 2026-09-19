import { api, settle } from "@/lib/api";
import { Terminal } from "@/components/terminal/Terminal";

/** Server entry: read the live system once, hand it to the client screen, which then streams and polls. */
export default async function TerminalPage() {
  const [status, treasury, quotes, events, metrics, strategies] = await Promise.all([
    settle(api.status()),
    settle(api.treasury()),
    settle(api.quotes()),
    settle(api.events(240)),
    settle(api.treasuryMetrics()),
    settle(api.strategies()),
  ]);
  return <Terminal initial={{ status, treasury, quotes, events: events ?? [], metrics, strategies: strategies ?? [] }} />;
}
