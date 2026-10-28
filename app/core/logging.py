"""Structured JSON logs to stdout. One line per event, easy to grep in Railway logs."""
import json
import logging
import sys
from datetime import datetime, timezone

from app.settings import settings

_logger = logging.getLogger("voice_agent")


def configure_logging() -> None:
    if _logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(settings.log_level.upper())
    _logger.propagate = False


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    _logger.log(level, json.dumps(record, default=str))
