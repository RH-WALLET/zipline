"""`zl` — operator command line."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date
from decimal import Decimal
from typing import Annotated

import typer

from zipline_engine.config import get_settings
from zipline_engine.logging_setup import configure_logging

app = typer.Typer(no_args_is_help=True, help="ZIPLINE engine operator CLI", add_completion=False)
demo_app = typer.Typer(help="DEMO MODE helpers (simulated treasury only)")
strategy_app = typer.Typer(help="Enable/disable strategies")
treasury_app = typer.Typer(help="Treasury operations")
app.add_typer(demo_app, name="demo")
app.add_typer(strategy_app, name="strategy")
app.add_typer(treasury_app, name="treasury")

log = logging.getLogger("zl")


def _setup() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.secret_values())


def _runtime():  # type: ignore[no-untyped-def]
    from zipline_engine.db.base import session_scope
    from zipline_engine.runtime import build_runtime

    return session_scope, build_runtime


@app.command("init-db")
def init_db() -> None:
    """Run database migrations (alembic upgrade head)."""
    _setup()
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"])


@app.command()
def bootstrap() -> None:
    """Create strategies, allocations, sleeves and (demo) seed funding. Idempotent."""
    _setup()
    from zipline_engine.scheduler.bootstrap import bootstrap as _bootstrap

    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        _bootstrap(rt)
    typer.echo("bootstrap complete")


@app.command()
def universe() -> None:
    """Refresh the Stock Token universe and print eligibility."""
    _setup()
    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        report = rt.universe.refresh()
        typer.echo(
            json.dumps(
                {
                    "source": report.source,
                    "eligible": report.eligible,
                    "hold_only": report.hold_only,
                    "ineligible": report.ineligible,
                    "error": report.error,
                },
                indent=2,
            )
        )


@app.command("load-history")
def load_history(
    symbols: Annotated[str | None, typer.Option(help="comma-separated; default allowlist")] = None,
    force: bool = False,
) -> None:
    """Fetch/refresh cached historical underlying bars."""
    _setup()
    from zipline_engine.core.calendar import last_completed_session

    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        syms = [s.strip().upper() for s in symbols.split(",")] if symbols else rt.settings.allowlist
        report = rt.marketdata.refresh(syms, last_completed_session(), force_full=force)
        typer.echo(
            json.dumps(
                {
                    "provider": report.provider,
                    "fetched": report.fetched,
                    "unchanged": report.unchanged,
                    "failed": report.failed,
                    "unavailable": report.unavailable,
                },
                indent=2,
            )
        )


@app.command("run-cycle")
def run_cycle_cmd(
    force: bool = False, session_date: Annotated[str | None, typer.Option(help="YYYY-MM-DD")] = None
) -> None:
    """Run one full strategy cycle (signals -> netting -> execution -> reconciliation)."""
    _setup()
    from zipline_engine.scheduler.bootstrap import bootstrap as _bootstrap
    from zipline_engine.scheduler.cycle import run_cycle

    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        _bootstrap(rt)
        cycle = run_cycle(
            rt, force=force, session_date=date.fromisoformat(session_date) if session_date else None
        )
        typer.echo(
            json.dumps(
                {"cycle_id": cycle.id, "status": cycle.status, "summary": cycle.summary},
                indent=2,
                default=str,
            )
        )


@app.command()
def reconcile() -> None:
    """Compare sleeve books against the treasury; pause on a break."""
    _setup()
    from zipline_engine.scheduler.cycle import run_reconciliation

    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        ev = run_reconciliation(rt, trigger="cli")
        typer.echo(
            json.dumps(
                {
                    "status": ev.status,
                    "max_break_bps": str(ev.max_break_bps),
                    "cash_break": str(ev.cash_break),
                    "position_breaks": ev.position_breaks,
                },
                indent=2,
            )
        )


@app.command()
def revalue() -> None:
    """Mark books and take a treasury snapshot with live prices."""
    _setup()
    from zipline_engine.scheduler.cycle import run_valuation

    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        v = run_valuation(rt, refresh_universe=True)
        typer.echo(
            json.dumps(
                {
                    "nav": str(v.nav),
                    "cash": str(v.cash),
                    "positions_value": str(v.positions_value),
                    "gas_eth": str(v.gas_eth),
                },
                indent=2,
            )
        )


@app.command()
def status() -> None:
    """Print mode, blockers and system state."""
    _setup()
    from zipline_engine.core.system import get_state

    session_scope, build_runtime = _runtime()
    s = get_settings()
    with session_scope() as session:
        st = get_state(session)
        typer.echo(
            json.dumps(
                {
                    "live_trading": s.live_trading,
                    "treasury_mode": s.treasury_mode,
                    "paused": st.paused,
                    "pause_reason": st.pause_reason,
                    "live_trading_blockers": s.live_trading_blockers(),
                    "last_cycle_at": str(st.last_cycle_at),
                    "last_reconciliation": st.last_reconciliation_status,
                    "config": s.public_dict(),
                },
                indent=2,
                default=str,
            )
        )


@app.command()
def pause(reason: str = "operator") -> None:
    _setup()
    from zipline_engine.core.system import pause as _pause
    from zipline_engine.events.bus import EventBus

    session_scope, _ = _runtime()
    with session_scope() as session:
        _pause(session, EventBus(session), reason)
    typer.echo("paused")


@app.command()
def resume() -> None:
    _setup()
    from zipline_engine.core.system import resume as _resume
    from zipline_engine.events.bus import EventBus

    session_scope, _ = _runtime()
    with session_scope() as session:
        _resume(session, EventBus(session), "cli")
    typer.echo("resumed")


@app.command()
def worker() -> None:
    """Run the scheduler (daily cycle, valuation, reconciliation, funding scan)."""
    from zipline_engine.scheduler.worker import main

    main()


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("zipline_engine.api.app:app", host=host, port=port, reload=reload)


@app.command()
def backtest(
    strategy: str,
    start: Annotated[str, typer.Option(help="YYYY-MM-DD")],
    end: Annotated[str, typer.Option(help="YYYY-MM-DD")],
    capital: float = 10000.0,
    bundle: str = "zipline-rh-history",
) -> None:
    """Backtest a strategy with zipline-reloaded against the cached historical bars."""
    _setup()
    from zipline_engine.zipline_bridge.backtest import run_backtest

    stats = run_backtest(
        strategy.upper(),
        date.fromisoformat(start),
        date.fromisoformat(end),
        capital_base=capital,
        bundle=bundle,
    )
    typer.echo(json.dumps(stats, indent=2, default=str))


@app.command("ingest-bundle")
def ingest_bundle(bundle: str = "zipline-rh-history") -> None:
    """Build a zipline data bundle from the cached historical bars."""
    _setup()
    from zipline_engine.zipline_bridge.bundle import ingest

    path = ingest(bundle)
    typer.echo(f"bundle {bundle} ingested at {path}")


@demo_app.command("deposit")
def demo_deposit(amount: float) -> None:
    """Credit the SIMULATED treasury (demo mode only) and record a contribution."""
    _setup()
    from zipline_engine.core.money import D
    from zipline_engine.db.enums import FundingKind
    from zipline_engine.scheduler.cycle import run_valuation

    session_scope, build_runtime = _runtime()
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        if rt.simulated is None:
            raise typer.BadParameter("demo deposits exist only for TREASURY_MODE=simulated")
        rt.simulated.deposit_cash(D(amount))
        rt.funding.record_funding(
            FundingKind.CONTRIBUTION, D(amount), note="SIMULATED deposit via CLI"
        )
        run_valuation(rt)
    typer.echo(f"simulated deposit of {amount} recorded")


@treasury_app.command("withdraw")
def treasury_withdraw(
    amount: float,
    to: Annotated[str | None, typer.Option(help="recipient address")] = None,
    tx_hash: Annotated[
        str | None, typer.Option(help="hash of an already-sent transfer to record")
    ] = None,
    broadcast: bool = typer.Option(
        False, help="LIVE: sign and send the ERC-20 transfer from the treasury"
    ),
) -> None:
    """Record (or, with --broadcast in live mode, execute) an operator withdrawal."""
    _setup()
    from zipline_engine.scheduler.withdraw import record_withdrawal

    session_scope, build_runtime = _runtime()
    if broadcast:
        typer.confirm(
            f"Send {amount} {get_settings().cash_token_symbol} from the treasury to {to}?",
            abort=True,
        )
    with session_scope() as session:
        rt = build_runtime(session, get_settings())
        ev = record_withdrawal(
            rt,
            Decimal(str(amount)),
            to_address=to,
            tx_hash=tx_hash,
            note="cli",
            broadcast=broadcast,
        )
        typer.echo(
            json.dumps(
                {
                    "id": ev.id,
                    "status": ev.status,
                    "tx_hash": ev.tx_hash,
                    "deallocation": ev.deallocation,
                },
                indent=2,
            )
        )


@strategy_app.command("enable")
def strategy_enable(code: str) -> None:
    _set_enabled(code, True)


@strategy_app.command("disable")
def strategy_disable(code: str) -> None:
    _set_enabled(code, False)


def _set_enabled(code: str, enabled: bool) -> None:
    _setup()
    from sqlalchemy import select

    from zipline_engine.db.enums import EventType
    from zipline_engine.db.models import Strategy
    from zipline_engine.events.bus import EventBus

    session_scope, _ = _runtime()
    with session_scope() as session:
        s = session.execute(
            select(Strategy).where(Strategy.code == code.upper())
        ).scalar_one_or_none()
        if s is None:
            raise typer.BadParameter(f"unknown strategy {code}")
        prev = s.status
        s.enabled = enabled
        s.status = "ACTIVE" if enabled else "DISABLED"
        s.status_reason = ("re-enabled" if enabled else "disabled") + " by operator (cli)"
        EventBus(session).emit(
            EventType.STRATEGY_STATUS_CHANGED,
            f"{s.code}: {prev} -> {s.status} ({s.status_reason})",
            payload={"strategy": s.code, "from": prev, "to": s.status},
        )
    typer.echo(f"{code.upper()} {'enabled' if enabled else 'disabled'}")


if __name__ == "__main__":
    app()
