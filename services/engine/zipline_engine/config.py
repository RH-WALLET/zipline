"""Runtime configuration.

Everything comes from environment variables (or a .env file). Secrets are held in
``SecretStr`` and never appear in ``repr``, logs, or API responses.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TreasuryMode = Literal["simulated", "onchain"]
HistoryProvider = Literal["yfinance", "stooq", "polygon", "alpaca", "twelvedata"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: str = "development"
    log_level: str = "INFO"

    # --- mode ---------------------------------------------------------------
    live_trading: bool = False
    treasury_mode: TreasuryMode = "simulated"
    demo_initial_cash: Decimal = Decimal("5000")
    demo_initial_gas_eth: Decimal = Decimal("0.05")

    # --- database -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://zipline:zipline@localhost:5433/zipline"

    # --- chain --------------------------------------------------------------
    chain_id: int = 4663
    rh_rpc_url: str = ""
    explorer_base_url: str = "https://robinhoodchain.blockscout.com"
    executor_address: str = ""
    executor_private_key: SecretStr = SecretStr("")
    cash_token_address: str = ""
    cash_token_symbol: str = "USDG"

    # --- robinhood stock token api ------------------------------------------
    rh_stock_token_api_url: str = "https://api.robinhood.com/rhj"
    asset_allowlist: str = (
        "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AVGO,AMD,COST,XOM,SPY,QQQ,VTI,GLD,BND"
    )
    pairs_candidates: str = "SPY:QQQ,SPY:VTI,AAPL:MSFT,GOOGL:META,NVDA:AMD"

    # --- execution provider -------------------------------------------------
    zerox_api_url: str = "https://api.0x.org"
    zerox_api_key: SecretStr = SecretStr("")

    # --- historical data ----------------------------------------------------
    history_provider: HistoryProvider = "yfinance"
    history_lookback_days: int = 420
    history_cache_dir: str = "data/history"
    polygon_api_key: SecretStr = SecretStr("")
    alpaca_api_key: SecretStr = SecretStr("")
    alpaca_api_secret: SecretStr = SecretStr("")
    twelvedata_api_key: SecretStr = SecretStr("")

    # --- schedule -----------------------------------------------------------
    cycle_time_et: str = "16:20"
    valuation_interval_min: int = 15
    reconcile_interval_min: int = 60
    funding_scan_interval_min: int = 5
    universe_refresh_interval_min: int = 60

    # --- capital & risk (percent of treasury NAV unless stated) -------------
    cash_reserve_pct: Decimal = Decimal("10")
    max_single_asset_pct: Decimal = Decimal("20")
    max_strategy_allocation_pct: Decimal = Decimal("20")
    max_order_pct_of_treasury: Decimal = Decimal("10")
    max_daily_turnover_pct: Decimal = Decimal("50")
    min_trade_notional_pct: Decimal = Decimal("0.25")
    max_slippage_bps: int = 100
    max_price_impact_bps: int = 150
    max_failed_txs_before_pause: int = 3
    price_staleness_sec: int = 120
    quote_staleness_sec: int = 30
    min_gas_eth: Decimal = Decimal("0.002")
    reconciliation_tolerance_bps: int = 10
    watch_drawdown_pct: Decimal = Decimal("10")
    disable_drawdown_pct: Decimal = Decimal("25")

    # --- gas pricing ----------------------------------------------------------
    eth_usd_price_source: Literal["coinbase", "chainlink", "none"] = "coinbase"
    chainlink_eth_usd_feed: str = ""

    # --- admin ----------------------------------------------------------------
    admin_token: SecretStr = SecretStr("")

    # --- optional project token (never traded) -------------------------------
    project_token_address: str = ""

    @field_validator("executor_address", "cash_token_address", "project_token_address")
    @classmethod
    def _strip_addr(cls, v: str) -> str:
        return v.strip()

    # ------------------------------------------------------------------------
    @property
    def allowlist(self) -> list[str]:
        return [s.strip().upper() for s in self.asset_allowlist.split(",") if s.strip()]

    @property
    def pairs(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for item in self.pairs_candidates.split(","):
            if ":" in item:
                a, b = item.split(":", 1)
                out.append((a.strip().upper(), b.strip().upper()))
        return out

    @property
    def is_demo(self) -> bool:
        return not self.live_trading

    @property
    def onchain_readable(self) -> bool:
        return bool(self.rh_rpc_url) and bool(self.executor_address)

    def live_trading_blockers(self) -> list[str]:
        """Why live trading cannot be enabled right now (empty list == all clear)."""
        problems: list[str] = []
        if not self.live_trading:
            problems.append("LIVE_TRADING is false")
        if self.treasury_mode != "onchain":
            problems.append("TREASURY_MODE must be 'onchain'")
        if not self.rh_rpc_url:
            problems.append("RH_RPC_URL is not set")
        if not self.executor_address:
            problems.append("EXECUTOR_ADDRESS is not set")
        if not self.executor_private_key.get_secret_value():
            problems.append("EXECUTOR_PRIVATE_KEY is not set")
        if not self.cash_token_address:
            problems.append("CASH_TOKEN_ADDRESS is not set")
        if not self.zerox_api_key.get_secret_value():
            problems.append("ZEROX_API_KEY is not set")
        if self.chain_id != 4663:
            problems.append(f"CHAIN_ID is {self.chain_id}, expected 4663 (Robinhood Chain)")
        return problems

    def secret_values(self) -> list[str]:
        """Every secret string that must be redacted from logs and error messages."""
        vals = [
            self.executor_private_key.get_secret_value(),
            self.zerox_api_key.get_secret_value(),
            self.polygon_api_key.get_secret_value(),
            self.alpaca_api_key.get_secret_value(),
            self.alpaca_api_secret.get_secret_value(),
            self.twelvedata_api_key.get_secret_value(),
            self.admin_token.get_secret_value(),
        ]
        pk = self.executor_private_key.get_secret_value()
        if pk.startswith("0x"):
            vals.append(pk[2:])
        elif pk:
            vals.append("0x" + pk)
        return [v for v in vals if v and len(v) >= 8]

    def public_dict(self) -> dict[str, object]:
        """Configuration safe to expose through the API. No secrets, ever."""
        return {
            "app_env": self.app_env,
            "live_trading": self.live_trading,
            "treasury_mode": self.treasury_mode,
            "chain_id": self.chain_id,
            "explorer_base_url": self.explorer_base_url,
            "executor_address": self.executor_address or None,
            "cash_token_address": self.cash_token_address or None,
            "cash_token_symbol": self.cash_token_symbol,
            "history_provider": self.history_provider,
            "cycle_time_et": self.cycle_time_et,
            "allowlist": self.allowlist,
            "risk": {
                "cash_reserve_pct": str(self.cash_reserve_pct),
                "max_single_asset_pct": str(self.max_single_asset_pct),
                "max_strategy_allocation_pct": str(self.max_strategy_allocation_pct),
                "max_order_pct_of_treasury": str(self.max_order_pct_of_treasury),
                "max_daily_turnover_pct": str(self.max_daily_turnover_pct),
                "min_trade_notional_pct": str(self.min_trade_notional_pct),
                "max_slippage_bps": self.max_slippage_bps,
                "max_price_impact_bps": self.max_price_impact_bps,
                "max_failed_txs_before_pause": self.max_failed_txs_before_pause,
                "reconciliation_tolerance_bps": self.reconciliation_tolerance_bps,
                "watch_drawdown_pct": str(self.watch_drawdown_pct),
                "disable_drawdown_pct": str(self.disable_drawdown_pct),
            },
            "project_token_address": self.project_token_address or None,
            "zerox_configured": bool(self.zerox_api_key.get_secret_value()),
            "rpc_configured": bool(self.rh_rpc_url),
            "signer_configured": bool(self.executor_private_key.get_secret_value()),
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
