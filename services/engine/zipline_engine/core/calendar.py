"""US equity trading calendar helpers (XNYS via exchange-calendars, the Zipline lineage)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

ET = ZoneInfo("America/New_York")


@lru_cache(maxsize=1)
def nyse() -> xcals.ExchangeCalendar:
    start = pd.Timestamp("2000-01-01")
    end = pd.Timestamp.now(tz=UTC).tz_localize(None).normalize() + pd.Timedelta(days=400)
    return xcals.get_calendar("XNYS", start=start, end=end)


def is_session(day: date) -> bool:
    return bool(nyse().is_session(pd.Timestamp(day)))


def sessions_between(start: date, end: date) -> list[date]:
    idx = nyse().sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))
    return [ts.date() for ts in idx]


def last_completed_session(now: datetime | None = None) -> date:
    """The most recent session whose regular close is at or before ``now``."""
    now = now or datetime.now(UTC)
    ts = pd.Timestamp(now).tz_convert(UTC) if now.tzinfo else pd.Timestamp(now, tz=UTC)
    cal = nyse()
    session = cal.date_to_session(ts.tz_localize(None).normalize(), direction="previous")
    close = cal.session_close(session)
    if close > ts:
        session = cal.previous_session(session)
    return session.date()


def next_session(day: date) -> date:
    return nyse().next_session(pd.Timestamp(day)).date()


def previous_session(day: date) -> date:
    return nyse().previous_session(pd.Timestamp(day)).date()


def session_close_utc(day: date) -> datetime:
    return nyse().session_close(pd.Timestamp(day)).to_pydatetime()


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def next_cycle_time(cycle_time_et: str, now: datetime | None = None) -> datetime:
    """Next wall-clock instant (UTC) at which a daily cycle should run.

    The cycle runs at ``cycle_time_et`` (Eastern) on every trading session, after the
    close. If today's run time has passed, it is the next session's.
    """
    now = now or datetime.now(UTC)
    t = parse_hhmm(cycle_time_et)
    now_et = now.astimezone(ET)
    candidate_day = now_et.date()
    for _ in range(10):
        if is_session(candidate_day):
            run_at = datetime.combine(candidate_day, t, tzinfo=ET)
            if run_at > now_et:
                return run_at.astimezone(UTC)
        candidate_day = candidate_day + timedelta(days=1)
    raise RuntimeError("no trading session found in the next 10 days")


def session_index(day: date, origin: date = date(2000, 1, 3)) -> int:
    """Deterministic ordinal of a session (number of sessions since ``origin``)."""
    return len(sessions_between(origin, day)) - 1


def market_state(now: datetime | None = None) -> dict[str, object]:
    """Whether NYSE's regular session is open right now, and the next open/close instants (UTC)."""
    now = now or datetime.now(UTC)
    ts = pd.Timestamp(now).tz_convert(UTC) if now.tzinfo else pd.Timestamp(now, tz=UTC)
    cal = nyse()
    is_open = bool(cal.is_open_on_minute(ts))
    next_open = cal.next_open(ts)
    next_close = cal.next_close(ts)
    return {
        "exchange": "XNYS",
        "is_open": is_open,
        "next_open": next_open.to_pydatetime(),
        "next_close": next_close.to_pydatetime(),
    }
