"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from zipline_engine import __version__
from zipline_engine.api.routes import admin, metrics, public, quotes, stream
from zipline_engine.config import get_settings
from zipline_engine.logging_setup import configure_logging, redact

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    log.info(
        "ZIPLINE engine API %s starting (live_trading=%s, treasury_mode=%s)",
        __version__,
        settings.live_trading,
        settings.treasury_mode,
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ZIPLINE engine",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
    )
    app.include_router(public.router)
    app.include_router(metrics.router)
    app.include_router(quotes.router)
    app.include_router(stream.router)
    app.include_router(admin.router)

    @app.exception_handler(Exception)
    async def _unhandled(
        request: Request, exc: Exception
    ) -> JSONResponse:  # secrets never leak via errors
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": redact(f"{type(exc).__name__}: {exc}")[:500]}
        )

    return app


app: Any = create_app()
