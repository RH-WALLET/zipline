/** Server-side access to the engine. Never cached: every render reads the live system. */

import type {
  Asset,
  Cross,
  Metrics,
  Cycle,
  Execution,
  Fill,
  FundingEvent,
  PortfolioSnapshot,
  QuoteBoard,
  Reconciliation,
  Signal,
  Status,
  Strategy,
  StrategyDetail,
  SystemEvent,
  Treasury,
  TreasurySnapshot,
  Tx,
  WithdrawalEvent,
} from "./types";

export const ENGINE_URL = process.env.ENGINE_URL ?? "http://localhost:8000";

export class EngineUnavailable extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EngineUnavailable";
  }
}

async function get<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${ENGINE_URL}${path}`, { cache: "no-store", headers: { accept: "application/json" } });
  } catch (e) {
    throw new EngineUnavailable(`engine unreachable at ${ENGINE_URL}: ${(e as Error).message}`);
  }
  if (!res.ok) throw new EngineUnavailable(`engine ${path} -> HTTP ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  status: () => get<Status>("/status"),
  treasury: () => get<Treasury>("/treasury"),
  treasuryHistory: (limit = 500) => get<TreasurySnapshot[]>(`/treasury/history?limit=${limit}`),
  treasuryMetrics: () => get<Metrics>("/treasury/metrics"),
  strategyMetrics: (code: string) => get<Metrics>(`/strategies/${encodeURIComponent(code)}/metrics`),
  funding: () => get<{ funding: FundingEvent[]; withdrawals: WithdrawalEvent[] }>("/treasury/funding"),
  assets: () => get<Asset[]>("/assets"),
  quotes: () => get<QuoteBoard>("/quotes"),
  strategies: () => get<Strategy[]>("/strategies"),
  strategy: (code: string) => get<StrategyDetail>(`/strategies/${encodeURIComponent(code)}`),
  strategyHistory: (code: string, limit = 500) => get<PortfolioSnapshot[]>(`/strategies/${encodeURIComponent(code)}/history?limit=${limit}`),
  strategySignals: (code: string, limit = 200) => get<Signal[]>(`/strategies/${encodeURIComponent(code)}/signals?limit=${limit}`),
  strategyFills: (code: string, limit = 200) => get<Fill[]>(`/strategies/${encodeURIComponent(code)}/fills?limit=${limit}`),
  strategyCrosses: (code: string, limit = 200) => get<Cross[]>(`/strategies/${encodeURIComponent(code)}/crosses?limit=${limit}`),
  strategyExecutions: (code: string, limit = 200) => get<Execution[]>(`/strategies/${encodeURIComponent(code)}/executions?limit=${limit}`),
  signals: (limit = 100) => get<Signal[]>(`/signals?limit=${limit}`),
  executions: (limit = 200) => get<Execution[]>(`/executions?limit=${limit}`),
  transactions: (limit = 200) => get<Tx[]>(`/transactions?limit=${limit}`),
  crosses: (limit = 100) => get<Cross[]>(`/crosses?limit=${limit}`),
  fills: (limit = 200) => get<Fill[]>(`/fills?limit=${limit}`),
  reconciliation: (limit = 50) => get<Reconciliation[]>(`/reconciliation?limit=${limit}`),
  events: (limit = 200) => get<SystemEvent[]>(`/events?limit=${limit}`),
  cycles: (limit = 50) => get<Cycle[]>(`/cycles?limit=${limit}`),
};

/** Resolve several requests; a failure of one does not blank the whole page. */
export async function settle<T>(p: Promise<T>): Promise<T | null> {
  try {
    return await p;
  } catch {
    return null;
  }
}
