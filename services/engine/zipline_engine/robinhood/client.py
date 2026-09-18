"""Client for Robinhood's public Stock Token REST APIs.

Base URL: https://api.robinhood.com/rhj/   (no authentication; rate limit 60 req/s)

  GET /assets                 asset metadata, deployments per chain, corporate-action multiplier
  GET /prices/{symbol}        underlying bid/ask (NOT multiplier adjusted), halt flag, volume
  GET /corporate-actions      splits / dividends with status

Field names below mirror the documented JSON exactly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from zipline_engine.core.money import D

log = logging.getLogger(__name__)


class RHDeployment(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    contractAddress: str
    chainId: int

    @field_validator("chainId", mode="before")
    @classmethod
    def _int_chain(cls, v: Any) -> int:
        return int(v)


TRADABLE = "TRADING_STATUS_TRADABLE"


class RHTradingCapabilities(BaseModel):
    """Two shapes are accepted: the documented booleans, and the live nested form
    ``{market: {whole, fractional}, extended: {...}, overnight: {...}}`` with TRADING_STATUS_* values."""

    model_config = ConfigDict(extra="ignore")
    fractionalTradability: bool | None = None
    allDayTradability: bool | None = None
    extendedHoursFractionalTradability: bool | None = None
    market: dict[str, Any] | None = None
    extended: dict[str, Any] | None = None
    overnight: dict[str, Any] | None = None

    @staticmethod
    def _tradable(session: dict[str, Any] | None, key: str) -> bool:
        return bool(session) and session.get(key) == TRADABLE  # type: ignore[union-attr]

    @property
    def fractional_tradable(self) -> bool:
        if self.fractionalTradability is not None:
            return self.fractionalTradability
        return self._tradable(self.market, "fractional")

    @property
    def all_day_tradable(self) -> bool:
        if self.allDayTradability is not None:
            return self.allDayTradability
        return self._tradable(self.overnight, "fractional") or self._tradable(
            self.overnight, "whole"
        )

    @property
    def extended_fractional_tradable(self) -> bool:
        if self.extendedHoursFractionalTradability is not None:
            return self.extendedHoursFractionalTradability
        return self._tradable(self.extended, "fractional")

    @property
    def any_tradable(self) -> bool:
        if self.fractionalTradability is not None or self.market is not None:
            return self.fractional_tradable or self._tradable(self.market, "whole")
        return True  # capabilities not reported: do not block on them


class RHAsset(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    tokenSymbol: str
    tokenName: str = ""
    deployments: list[RHDeployment] = Field(default_factory=list)
    currentMultiplier: Decimal = Decimal(1)
    pendingMultiplier: Decimal | None = None
    pendingMultiplierEffectiveTime: datetime | None = None
    logoUrl: str | None = None
    tradingCapabilities: RHTradingCapabilities = Field(default_factory=RHTradingCapabilities)
    status: str = "ASSET_STATUS_UNSPECIFIED"
    tokenDecimals: int = 18
    isin: str | None = None

    @field_validator("currentMultiplier", "pendingMultiplier", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal | None:
        if v is None or v == "":
            return None
        return D(v)

    @property
    def symbol(self) -> str:
        return self.tokenSymbol.upper()

    def deployment_on(self, chain_id: int) -> RHDeployment | None:
        for d in self.deployments:
            if d.chainId == chain_id:
                return d
        return None


class RHPrice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tokenSymbol: str
    deployments: list[RHDeployment] = Field(default_factory=list)
    bid: Decimal | None = None
    ask: Decimal | None = None
    currency: str = "USD"
    dailyTradingVolume: Decimal | None = None
    isTradingHalt: bool = False
    generatedAt: datetime | None = None

    @field_validator("bid", "ask", "dailyTradingVolume", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal | None:
        if v is None or v == "":
            return None
        return D(v)

    @property
    def mid(self) -> Decimal | None:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return (self.bid + self.ask) / 2

    @property
    def valid(self) -> bool:
        return (
            self.mid is not None
            and self.ask is not None
            and self.bid is not None
            and self.ask >= self.bid
        )


class RHCorporateAction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = ""
    type: str
    status: str
    processDate: str | None = None
    tokenSymbol: str
    deployments: list[RHDeployment] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("processDate", mode="before")
    @classmethod
    def _date(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        if isinstance(v, dict) and {"year", "month", "day"} <= set(v):
            return f"{int(v['year']):04d}-{int(v['month']):02d}-{int(v['day']):02d}"
        return str(v)

    @property
    def is_split(self) -> bool:
        return self.type in (
            "CORPORATE_ACTION_TYPE_FORWARD_SPLIT",
            "CORPORATE_ACTION_TYPE_REVERSE_SPLIT",
        )


class RobinhoodAPIError(RuntimeError):
    pass


def _extract_list(payload: Any, *keys: str) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys:
            if isinstance(payload.get(k), list):
                return payload[k]
        for v in payload.values():
            if isinstance(v, list):
                return v
    return []


class RobinhoodStockTokenClient:
    def __init__(
        self, base_url: str, client: httpx.Client | None = None, timeout: float = 15.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"accept": "application/json", "user-agent": "zipline-engine/0.1"},
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            r = self._client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            raise RobinhoodAPIError(f"{path}: HTTP {e.response.status_code}") from e
        except (httpx.HTTPError, ValueError) as e:
            raise RobinhoodAPIError(f"{path}: {type(e).__name__}: {e}") from e

    def list_assets(self) -> list[RHAsset]:
        payload = self._get("/assets")
        out: list[RHAsset] = []
        for item in _extract_list(payload, "assets", "results", "data"):
            try:
                out.append(RHAsset.model_validate(item))
            except Exception as e:  # skip malformed entries but keep going
                log.warning("skipping malformed asset entry: %s", e)
        return out

    def get_price(self, symbol: str) -> RHPrice:
        payload = self._get(f"/prices/{symbol.upper()}")
        if isinstance(payload, dict) and "tokenSymbol" not in payload:
            items = _extract_list(payload, "quotes", "prices", "results", "data")
            if items:
                payload = items[0]
        return RHPrice.model_validate(payload)

    def get_prices(self, symbols: list[str]) -> dict[str, RHPrice | Exception]:
        out: dict[str, RHPrice | Exception] = {}
        for s in symbols:
            try:
                out[s.upper()] = self.get_price(s)
            except Exception as e:
                out[s.upper()] = e
        return out

    def list_corporate_actions(self) -> list[RHCorporateAction]:
        payload = self._get("/corporate-actions")
        out: list[RHCorporateAction] = []
        for item in _extract_list(
            payload, "corporateActions", "corporate_actions", "results", "data"
        ):
            try:
                out.append(RHCorporateAction.model_validate(item))
            except Exception as e:
                log.warning("skipping malformed corporate action: %s", e)
        return out


def now_utc() -> datetime:
    return datetime.now(UTC)
