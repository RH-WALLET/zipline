"""Logging with secret redaction.

Known secret values (private key, API keys, admin token) are replaced with
``[REDACTED]`` in every log record. We deliberately do not blanket-redact 64-hex
strings, because transaction hashes are legitimate log content.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterable


class RedactionFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for s in self._secrets:
            if s in text:
                text = text.replace(s, "[REDACTED]")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = self.redact(msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


_FILTER: RedactionFilter | None = None


def configure_logging(level: str, secrets: Iterable[str]) -> RedactionFilter:
    global _FILTER
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", "%Y-%m-%dT%H:%M:%S")
    )
    _FILTER = RedactionFilter(secrets)
    handler.addFilter(_FILTER)
    root.addHandler(handler)
    for noisy in (
        "httpx",
        "httpcore",
        "urllib3",
        "web3",
        "apscheduler",
        "yfinance",
        "peewee",
        "alembic",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return _FILTER


def redact(text: str) -> str:
    """Redact known secrets from arbitrary text (used for error messages persisted to DB)."""
    if _FILTER is None:
        return text
    return _FILTER.redact(text)
