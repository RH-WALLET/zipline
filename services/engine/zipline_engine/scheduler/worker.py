"""Worker process: daily cycle after the close, periodic valuation, reconciliation, funding scan."""

from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from zipline_engine.config import Settings, get_settings
from zipline_engine.core.calendar import ET, is_session, next_cycle_time, parse_hhmm
from zipline_engine.core.system import get_state
from zipline_engine.db.base import session_scope
from zipline_engine.db.enums import EventLevel, EventType
from zipline_engine.events.bus import EventBus
from zipline_engine.logging_setup import configure_logging, redact
from zipline_engine.runtime import build_runtime
from zipline_engine.scheduler.bootstrap import bootstrap
from zipline_engine.scheduler.cycle import CycleError, run_cycle, run_reconciliation, run_valuation
from zipline_engine.scheduler.funding_scan import scan_funding

log = logging.getLogger(__name__)
_LOCK = threading.Lock()


def _guarded(name: str, fn) -> None:  # type: ignore[no-untyped-def]
    if not _LOCK.acquire(blocking=False):
        log.info("%s skipped: another job is running", name)
        return
    try:
        fn()
    except CycleError as e:
        log.warning("%s: %s", name, e)
    except Exception as e:
        log.exception("%s failed", name)
        try:
            with session_scope() as session:
                EventBus(session).emit(
                    EventType.CONFIG_WARNING,
                    f"{name} failed: {type(e).__name__}: {redact(str(e))}",
                    level=EventLevel.ERROR,
                )
        except Exception:
            pass
    finally:
        _LOCK.release()


def job_cycle(settings: Settings) -> None:
    def _run() -> None:
        now_et = datetime.now(UTC).astimezone(ET)
        if not is_session(now_et.date()):
            log.info("no trading session today (%s); cycle skipped", now_et.date())
            return
        with session_scope() as session:
            rt = build_runtime(session, settings)
            run_cycle(rt)

    _guarded("daily cycle", _run)


def job_valuation(settings: Settings) -> None:
    def _run() -> None:
        with session_scope() as session:
            rt = build_runtime(session, settings)
            run_valuation(rt, refresh_universe=True)

    _guarded("valuation", _run)


def job_reconcile(settings: Settings) -> None:
    def _run() -> None:
        with session_scope() as session:
            rt = build_runtime(session, settings)
            run_reconciliation(rt, trigger="scheduled")

    _guarded("reconciliation", _run)


def job_funding(settings: Settings) -> None:
    def _run() -> None:
        with session_scope() as session:
            rt = build_runtime(session, settings)
            scan_funding(rt)

    _guarded("funding scan", _run)


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    with session_scope() as session:
        rt = build_runtime(session, settings)
        bootstrap(rt)
        st = get_state(session)
        st.next_cycle_at = next_cycle_time(settings.cycle_time_et)
        rt.events.emit(
            EventType.SYSTEM_STARTED,
            f"worker online: cycle daily at {settings.cycle_time_et} ET, valuation every {settings.valuation_interval_min}m, reconciliation every {settings.reconcile_interval_min}m, mode={'LIVE' if settings.live_trading else 'DRY_RUN'}",
            payload={
                "cycle_time_et": settings.cycle_time_et,
                "live_trading": settings.live_trading,
                "treasury_mode": settings.treasury_mode,
            },
        )
    t = parse_hhmm(settings.cycle_time_et)
    sched = BackgroundScheduler(timezone=ET)
    sched.add_job(
        job_cycle,
        CronTrigger(day_of_week="mon-fri", hour=t.hour, minute=t.minute, timezone=ET),
        args=[settings],
        id="cycle",
        misfire_grace_time=3600,
    )
    sched.add_job(
        job_valuation,
        IntervalTrigger(minutes=settings.valuation_interval_min),
        args=[settings],
        id="valuation",
        misfire_grace_time=300,
    )
    sched.add_job(
        job_reconcile,
        IntervalTrigger(minutes=settings.reconcile_interval_min),
        args=[settings],
        id="reconcile",
        misfire_grace_time=600,
    )
    sched.add_job(
        job_funding,
        IntervalTrigger(minutes=settings.funding_scan_interval_min),
        args=[settings],
        id="funding",
        misfire_grace_time=300,
    )
    sched.start()
    log.info(
        "worker started; next cycle at %s", next_cycle_time(settings.cycle_time_et).isoformat()
    )
    # one valuation right away so the dashboard is populated
    threading.Thread(target=job_valuation, args=(settings,), daemon=True).start()
    stop = threading.Event()

    def _stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not stop.is_set():
        time.sleep(1)
    sched.shutdown(wait=False)


if __name__ == "__main__":
    main()
