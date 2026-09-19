/** Shapes returned by the engine API. Decimals arrive as strings and stay strings until formatted. */

export type Mode = {
  live_trading: boolean;
  demo: boolean;
  treasury_mode: "simulated" | "onchain";
  execution_mode: "LIVE" | "DRY_RUN";
  paused: boolean;
  pause_reason: string | null;
  labels: string[];
};

export type Status = {
  mode: Mode;
  chain: {
    chain_id: number;
    explorer_base_url: string;
    rpc_configured: boolean;
    wallet_address: string | null;
    cash_token: { symbol: string; address: string | null };
  };
  system: {
    paused: boolean;
    pause_reason: string | null;
    paused_at: string | null;
    consecutive_failed_txs: number;
    bootstrapped_at: string | null;
    last_cycle: Cycle | null;
    last_cycle_at: string | null;
    next_cycle_at: string | null;
    last_completed_session: string;
    last_reconciliation_status: string | null;
    last_reconciliation_at: string | null;
    last_market_data_at: string | null;
    last_universe_refresh_at: string | null;
    cycle_time_et: string;
    market?: { exchange: string; is_open: boolean; next_open: string; next_close: string };
  };
  counts: {
    strategies: number;
    active_strategies: number;
    watch_strategies: number;
    disabled_strategies: number;
    positions: number;
    executions: number;
    real_transactions: number;
  };
  live_trading_blockers: string[];
  config: {
    history_provider: string;
    allowlist: string[];
    risk: Record<string, string | number>;
    project_token_address: string | null;
    cash_token_symbol: string;
    [k: string]: unknown;
  };
  software: { engine: string; zipline_reloaded: string };
};

export type TreasurySnapshot = {
  id: number;
  taken_at: string;
  mode: string;
  wallet_address: string | null;
  nav: string;
  cash_balance: string;
  positions_value: string;
  deployable_capital: string;
  reserved_cash: string;
  gas_balance_eth: string;
  gas_balance_usd: string | null;
  realized_pnl: string;
  unrealized_pnl: string;
  cumulative_gas_eth: string;
  cumulative_gas_usd: string;
  base_capital: string;
  contributions_total: string;
  withdrawals_total: string;
  twr_index: string;
  positions: Record<string, { quantity: string; underlying_mid: string; multiplier: string; token_price: string; value: string; price_source: string; stale: string }>;
};

export type Treasury = {
  mode: Mode;
  wallet_address: string | null;
  explorer_address_url: string | null;
  cash_token: { symbol: string; address: string | null };
  snapshot: TreasurySnapshot | null;
  returns: { total_return_pct: string | null; simple_return_pct?: string | null; trading_pnl: string | null; net_external_capital?: string };
  active_strategies: number;
  holdings: Record<string, { quantity: string; cost_basis: string; market_value: string; unrealized_pnl: string }>;
  treasury_positions: TreasurySnapshot["positions"];
};

export type StrategyState = {
  virtual_cash: string;
  allocated_capital: string;
  current_nav: string;
  peak_nav: string;
  realized_pnl: string;
  unrealized_pnl: string;
  max_drawdown_pct: string;
  current_drawdown_pct: string;
  cumulative_turnover: string;
  signals_count: number;
  fills_count: number;
  twr_index: string;
  last_rebalance_at: string | null;
  inception_at: string;
};

export type Position = {
  symbol: string;
  quantity: string;
  cost_basis: string;
  last_price: string | null;
  market_value: string;
  unrealized_pnl: string;
};

export type Strategy = {
  id: number;
  code: string;
  name: string;
  description: string;
  enabled: boolean;
  status: "ACTIVE" | "WATCH" | "DISABLED";
  status_reason: string | null;
  current_version_hash: string | null;
  weight_pct: string | null;
  allocation_policy: string | null;
  state: StrategyState | null;
  return_pct?: string;
  total_pnl?: string;
  age_days?: number | null;
  positions: Position[];
  position_symbols: string[];
};

export type StrategyDetail = Strategy & {
  versions: { version_hash: string; source_hash: string; params: Record<string, unknown>; rules: Record<string, unknown>; created_at: string }[];
  rules: Record<string, unknown> | null;
  params: Record<string, unknown> | null;
  source_hash: string | null;
  persisted_state: Record<string, unknown>;
  provenance: string[];
};

export type Signal = {
  id: number;
  cycle_id: number;
  strategy: string | null;
  symbol: string | null;
  session_date: string;
  kind: string;
  value: string | null;
  target_weight: string;
  previous_weight: string;
  version_hash: string;
  details: Record<string, unknown>;
  created_at: string;
};

export type Cross = {
  id: number;
  cycle_id: number;
  symbol: string | null;
  buyer: string | null;
  seller: string | null;
  quantity: string;
  price: string;
  notional: string;
  reference_price_source: string;
  created_at: string;
};

export type Tx = {
  id: number;
  kind: string;
  chain_id: number;
  tx_hash: string;
  from_address: string;
  to_address: string;
  gas_used: number | null;
  gas_cost_eth: string | null;
  gas_cost_usd: string | null;
  block_number: number | null;
  status: string;
  error: string | null;
  submitted_at: string;
  confirmed_at: string | null;
  explorer_url: string;
};

export type Execution = {
  id: number;
  local_id: string;
  cycle_id: number | null;
  symbol: string | null;
  side: "BUY" | "SELL";
  mode: "DRY_RUN" | "LIVE";
  adapter: string;
  status: string;
  requested_quantity: string;
  requested_notional: string;
  quoted_quantity: string | null;
  quoted_notional: string | null;
  executed_quantity: string | null;
  executed_notional: string | null;
  reference_price: string;
  expected_price: string | null;
  effective_price: string | null;
  slippage_bps: string | null;
  price_impact_bps: string | null;
  gas_used: number | null;
  gas_cost_eth: string | null;
  gas_cost_usd: string | null;
  reject_reason: string | null;
  contributions: { strategy: string; quantity: string }[];
  created_at: string;
  updated_at: string;
  quotes: unknown[];
  transactions: Tx[];
  is_real: boolean;
};

export type Fill = {
  id: number;
  cycle_id: number | null;
  strategy: string | null;
  symbol: string | null;
  side: "BUY" | "SELL";
  kind: "INTERNAL_CROSS" | "ONCHAIN_EXECUTION" | "DRY_RUN";
  quantity: string;
  price: string;
  notional: string;
  realized_pnl: string;
  internal_cross_id: number | null;
  execution_order_id: number | null;
  created_at: string;
};

export type Reconciliation = {
  id: number;
  run_at: string;
  mode: string;
  status: string;
  tolerance_bps: number;
  max_break_bps: string;
  cash_break: string;
  position_breaks: { symbol: string; books: string; treasury: string; diff: string; diff_bps: string }[];
  details: { trigger?: string; lines?: { symbol: string; books: string; treasury: string; diff: string; diff_bps: string }[]; buffer_cash?: string; reserve_target?: string; sleeve_cash?: string; treasury_cash?: string };
  triggered_pause: boolean;
};

export type SystemEvent = {
  id: number;
  created_at: string;
  type: string;
  level: "INFO" | "WARN" | "ERROR";
  message: string;
  cycle_id: number | null;
  payload: Record<string, unknown>;
};

export type Cycle = {
  id: number;
  session_date: string;
  mode: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  nav_at_start: string | null;
  summary: Record<string, unknown>;
  error: string | null;
};

export type Asset = {
  id: number;
  symbol: string;
  name: string;
  isin: string | null;
  status: string;
  current_multiplier: string;
  pending_multiplier: string | null;
  is_halted: boolean;
  in_allowlist: boolean;
  eligible: boolean;
  hold_only: boolean;
  eligibility_reasons: string[];
  fractional_tradability: boolean;
  all_day_tradability: boolean;
  last_seen_at: string | null;
  deployment: { chain_id: number; contract_address: string; decimals: number; verified_onchain: boolean; onchain_multiplier: string | null } | null;
  price: { bid: string; ask: string; mid: string; daily_volume: string | null; is_halted: boolean; generated_at: string | null; fetched_at: string } | null;
  explorer_token_url: string | null;
};

export type PortfolioSnapshot = {
  taken_at: string;
  nav: string;
  cash: string;
  positions_value: string;
  allocated_capital: string;
  realized_pnl: string;
  unrealized_pnl: string;
  drawdown_pct: string;
  twr_index: string;
};

export type FundingEvent = {
  id: number;
  kind: string;
  amount: string;
  asset_symbol: string;
  tx_hash: string | null;
  from_address: string | null;
  block_number: number | null;
  detected_at: string;
  allocated: boolean;
  allocation: { to_sleeves?: Record<string, string>; to_reserve?: string };
  note: string | null;
  explorer_url: string | null;
};

export type WithdrawalEvent = {
  id: number;
  amount: string;
  asset_symbol: string;
  to_address: string | null;
  tx_hash: string | null;
  status: string;
  requested_by: string;
  deallocation: Record<string, string>;
  created_at: string;
  note: string | null;
  explorer_url: string | null;
};

export type MetricSet = {
  total_return: number | null;
  annual_return: number | null;
  volatility: number | null;
  sharpe: number | null;
  calmar: number | null;
  stability: number | null;
  max_drawdown: number | null;
  omega: number | null;
  sortino: number | null;
  skew: number | null;
  kurtosis: number | null;
  tail_ratio: number | null;
  daily_var: number | null;
  alpha: number | null;
  beta: number | null;
  information_ratio: number | null;
  benchmark_return: number | null;
};

export type Metrics = {
  sessions: number;
  benchmark: string;
  overall: MetricSet;
  windows: Record<"1M" | "3M" | "6M" | "12M", MetricSet | null>;
  cumulative: { date: string; algorithm: number; benchmark?: number }[];
  drawdowns: { date: string; drawdown: number }[];
  daily_returns: { date: string; value: number }[];
  monthly: { year: number; month: number; value: number | null }[];
  intraday: { t: string; algorithm: number }[];
  note: string;
};

/** One row of the live quote board (GET /quotes). Underlying bid/ask; token values = price × multiplier. */
export type Quote = {
  symbol: string;
  name: string;
  multiplier: string;
  eligible: boolean;
  hold_only: boolean;
  status: string;
  source: "robinhood_api" | "cached_snapshot" | null;
  bid: string | null;
  ask: string | null;
  mid: string | null;
  spread_bps: string | null;
  token_bid: string | null;
  token_ask: string | null;
  token_mid: string | null;
  is_halted: boolean;
  daily_volume: string | null;
  generated_at: string | null;
  fetched_at: string | null;
  error: string | null;
};

export type QuoteBoard = {
  fetched_at: string;
  ttl_sec: number;
  source: string;
  live: number;
  cached: number;
  error: string | null;
  note: string;
  quotes: Quote[];
  age_sec: number;
};
