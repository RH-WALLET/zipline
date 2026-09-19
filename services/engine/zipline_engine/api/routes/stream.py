"""Server-sent events: the system event log, live."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from zipline_engine.api import serializers as ser
from zipline_engine.db.base import get_sessionmaker
from zipline_engine.db.models import SystemEvent

router = APIRouter()


def _fetch_after(after_id: int, limit: int = 200) -> list[dict[str, Any]]:
    session = get_sessionmaker()()
    try:
        rows = (
            session.execute(
                select(SystemEvent)
                .where(SystemEvent.id > after_id)
                .order_by(SystemEvent.id.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [ser.event(e) for e in rows]
    finally:
        session.close()


def _latest_id() -> int:
    session = get_sessionmaker()()
    try:
        row = session.execute(
            select(SystemEvent.id).order_by(SystemEvent.id.desc()).limit(1)
        ).scalar_one_or_none()
        return int(row or 0)
    finally:
        session.close()


@router.get("/events/stream")
async def events_stream(
    request: Request, after_id: int | None = Query(default=None)
) -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, Any]]:
        last = after_id if after_id is not None else await asyncio.to_thread(_latest_id)
        # Open the stream with a heartbeat so proxies flush headers and the browser's
        # EventSource reports "open" immediately instead of after the first idle interval.
        yield {"event": "heartbeat", "data": json.dumps({"last_id": last})}
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            events = await asyncio.to_thread(_fetch_after, last)
            if events:
                for ev in events:
                    last = max(last, int(ev["id"]))
                    yield {"event": "system_event", "id": str(ev["id"]), "data": json.dumps(ev)}
                idle = 0
            else:
                idle += 1
                if idle % 15 == 0:
                    yield {"event": "heartbeat", "data": json.dumps({"last_id": last})}
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen())
