"""Structured logging.

Privacy rule (docs/SECURITY_SPEC.md 5): logs may carry request/session/packet
identifiers, status and latency. They must NEVER carry transcript text, audio
bytes, tokens or API keys.

`redact` is the supported way to reference sensitive content, and
`SensitiveDataFilter` is a backstop that scrubs anything that slips through.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_TOKEN_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{4,}"),
]


def redact(value: str | None) -> str:
    """Replace sensitive content with a length-only marker."""
    if not value:
        return "<empty>"
    return f"<redacted:{len(value)}>"


class SensitiveDataFilter(logging.Filter):
    """Scrubs token-shaped substrings from any log record that reaches a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        scrubbed = message
        for pattern in _TOKEN_PATTERNS:
            scrubbed = pattern.sub(r"\1<redacted>", scrubbed)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, so logs are machine-readable without parsing prose."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "session_id", "packet_id", "event", "status", "latency_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            # Type and message only - no stack trace, which can carry paths
            # and local values (docs/SECURITY_SPEC.md 5).
            exc_type, exc_value, _ = record.exc_info
            payload["error_type"] = getattr(exc_type, "__name__", str(exc_type))
            payload["error_message"] = str(exc_value)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)
    # uvicorn's access log echoes full URLs; the app logs requests itself.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
