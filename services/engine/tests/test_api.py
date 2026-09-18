"""HTTP API: mode labels, admin auth, enable/disable, no secret leakage."""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeProvider, FakeRobinhood
from tests.test_integration_cycle import make_settings
from zipline_engine.api.app import create_app
from zipline_engine.config import get_settings
from zipline_engine.runtime import build_runtime
from zipline_engine.scheduler.bootstrap import bootstrap
from zipline_engine.scheduler.cycle import run_cycle

SECRET_KEY = "0x" + "ab" * 32


@pytest.fixture
def client(db_session, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("EXECUTOR_PRIVATE_KEY", SECRET_KEY)
    monkeypatch.setenv("ZEROX_API_KEY", "zx-super-secret")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    settings = make_settings(executor_private_key=SECRET_KEY, zerox_api_key="zx-super-secret")
    rt = build_runtime(db_session, settings)
    fake = FakeRobinhood(as_of=date(2026, 9, 15))
    rt.rh_client = fake  # type: ignore[assignment]
    rt.universe.rh = fake  # type: ignore[assignment]
    rt.pricing.rh = fake  # type: ignore[assignment]
    rt.marketdata.provider = FakeProvider()
    bootstrap(rt)
    run_cycle(rt, session_date=date(2026, 9, 15))
    db_session.commit()
    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_health_and_status_show_demo_mode(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    status = client.get("/status").json()
    assert status["mode"]["demo"] is True and status["mode"]["live_trading"] is False
    assert status["mode"]["labels"] == ["DEMO MODE", "LIVE TRADING DISABLED"]
    assert status["counts"]["strategies"] == 10 and status["counts"]["real_transactions"] == 0
    assert "LIVE_TRADING is false" in status["live_trading_blockers"]
    assert status["software"]["zipline_reloaded"]


def test_no_secret_ever_leaves_the_api(client: TestClient) -> None:
    for path in (
        "/status",
        "/treasury",
        "/strategies",
        "/assets",
        "/executions",
        "/events",
        "/reconciliation",
        "/cycles",
        "/treasury/funding",
    ):
        body = client.get(path).text
        assert (
            SECRET_KEY not in body
            and SECRET_KEY[2:] not in body
            and "zx-super-secret" not in body
            and "test-admin-token" not in body
        ), path
    cfg = client.get("/status").json()["config"]
    assert cfg["signer_configured"] is True and cfg["zerox_configured"] is True
    assert "executor_private_key" not in json.dumps(cfg)


def test_public_endpoints_shape(client: TestClient) -> None:
    strategies = client.get("/strategies").json()
    assert [s["code"] for s in strategies] == [
        "TREND",
        "MOMENTUM",
        "MEANREV",
        "BREAKOUT",
        "LOWVOL",
        "REVERSAL",
        "DUALMA",
        "RISKON",
        "PAIRS",
        "ZEROIQ",
    ]
    assert all(s["weight_pct"] == "10.000000" for s in strategies)
    detail = client.get("/strategies/ZEROIQ").json()
    assert detail["provenance"] == ["NO AI", "DETERMINISTIC", "REPRODUCIBLE", "RULE-BASED"]
    assert "seed" in detail["persisted_state"] and detail["rules"]["signal"].startswith("none")
    treasury = client.get("/treasury").json()
    assert treasury["snapshot"]["base_capital"] == "5000" and treasury["mode"]["demo"] is True
    execs = client.get("/executions").json()
    assert execs and all(
        e["mode"] == "DRY_RUN" and e["local_id"].startswith("dry-") and e["transactions"] == []
        for e in execs
    )
    assert client.get("/transactions").json() == []  # nothing real happened
    assert client.get("/strategies/NOPE").status_code == 404
    cyc = client.get("/cycles/1").json()
    assert cyc["cycle"]["status"] == "COMPLETED" and cyc["signals"] and cyc["executions"]
    events = client.get("/events?after_id=0&limit=5").json()
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)


def test_admin_requires_bearer_token(client: TestClient) -> None:
    assert client.post("/admin/pause", json={"note": "x"}).status_code == 401
    assert (
        client.post(
            "/admin/pause", json={"note": "x"}, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 403
    )
    ok = {"Authorization": "Bearer test-admin-token"}
    assert client.post("/admin/pause", json={"note": "test"}, headers=ok).json()["paused"] is True
    assert client.get("/status").json()["mode"]["paused"] is True
    assert client.post("/admin/run-cycle", headers=ok).status_code == 409  # paused: refuses
    assert client.post("/admin/resume", json={"note": "test"}, headers=ok).json()["paused"] is False


def test_admin_enable_disable_strategy(client: TestClient) -> None:
    ok = {"Authorization": "Bearer test-admin-token"}
    r = client.post("/admin/strategy/TREND/disable", json={"note": "test"}, headers=ok).json()
    assert r["status"] == "DISABLED" and r["enabled"] is False
    assert client.get("/strategies/TREND").json()["status"] == "DISABLED"
    r = client.post("/admin/strategy/TREND/enable", json={"note": "test"}, headers=ok).json()
    assert r["status"] == "ACTIVE" and r["enabled"] is True
    assert (
        client.post("/admin/strategy/NOPE/enable", json={"note": "x"}, headers=ok).status_code
        == 404
    )
    events = client.get("/events?type=STRATEGY_STATUS_CHANGED").json()
    assert len(events) >= 2


def test_admin_demo_deposit_records_contribution(client: TestClient) -> None:
    ok = {"Authorization": "Bearer test-admin-token"}
    r = client.post("/admin/demo/deposit", json={"amount": "250", "note": "test"}, headers=ok)
    assert r.status_code == 200 and r.json()["kind"] == "CONTRIBUTION"
    funding = client.get("/treasury/funding").json()["funding"]
    assert any(f["kind"] == "CONTRIBUTION" and f["amount"] == "250" for f in funding)
    assert client.get("/treasury").json()["snapshot"]["contributions_total"] == "250"


def test_metrics_endpoints_are_honest_about_history(client: TestClient) -> None:
    t = client.get("/treasury/metrics").json()
    assert (
        t["benchmark"] == "SPY"
        and "overall" in t
        and set(t["windows"]) == {"1M", "3M", "6M", "12M"}
    )
    # one session of snapshots: total return exists, ratios that need history are null, no window is filled
    assert t["sessions"] <= 1
    assert t["overall"]["sharpe"] is None and t["overall"]["alpha"] is None
    assert all(v is None for v in t["windows"].values())
    assert t["intraday"] and "algorithm" in t["intraday"][0]
    s = client.get("/strategies/TREND/metrics").json()
    assert (
        "total_return" in s["overall"] and s["cumulative"]
    )  # one point: since-inception 0%, no ratios
    assert client.get("/strategies/NOPE/metrics").status_code == 404
