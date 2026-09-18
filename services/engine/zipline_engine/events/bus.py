"""System event log. Every row is produced by real system activity; nothing is narrated."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from zipline_engine.db.enums import EventLevel, EventType
from zipline_engine.db.models import SystemEvent
from zipline_engine.logging_setup import redact

log = logging.getLogger("zipline.events")


class EventBus:
    def __init__(self, session: Session) -> None:
        self.session = session

    def emit(
        self,
        type_: EventType | str,
        message: str,
        *,
        level: EventLevel | str = EventLevel.INFO,
        payload: dict[str, Any] | None = None,
        cycle_id: int | None = None,
    ) -> SystemEvent:
        ev = SystemEvent(
            type=str(type_),
            level=str(level),
            message=redact(message)[:4000],
            payload=_jsonable(payload or {}),
            cycle_id=cycle_id,
        )
        self.session.add(ev)
        self.session.flush()
        log_fn = {"INFO": log.info, "WARN": log.warning, "ERROR": log.error}.get(
            str(level), log.info
        )
        log_fn("%s %s", ev.type, ev.message)
        return ev


def _jsonable(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, str):
        return redact(value)
    return value
