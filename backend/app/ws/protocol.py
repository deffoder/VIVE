"""WebSocket frame envelopes.

Mirrors docs/API_SPEC.md 6. Server frames carry a monotonic `seq` per session
so a client that detects a gap can backfill over REST with `since_seq` - that
is what makes reconnection safe rather than lossy.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ServerFrameType(StrEnum):
    SESSION_STATE = "session.state"
    PACKET_NEW = "packet.new"
    RISK_UPDATE = "risk.update"
    TRANSCRIPT_APPEND = "transcript.append"
    ALERT_RAISED = "alert.raised"
    SESSION_ENDED = "session.ended"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class ClientFrameType(StrEnum):
    AUDIO = "client.audio"
    """JSON-wrapped audio or a transcript hint. Binary frames are also accepted."""
    PAUSE = "client.pause"
    RESUME = "client.resume"
    END = "client.end"
    PONG = "client.pong"


class ServerFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ServerFrameType
    session_id: str
    seq: int = Field(ge=0)
    data: dict[str, Any] = Field(default_factory=dict)


class ClientFrame(BaseModel):
    """Inbound control frame.

    `extra="forbid"` so a malformed or unexpected field is rejected with a
    structured error rather than being silently ignored.
    """

    model_config = ConfigDict(extra="forbid")
    type: ClientFrameType
    transcript: str | None = Field(default=None, max_length=4_000)
    speaker: str | None = Field(default=None, max_length=64)
    audio_b64: str | None = Field(default=None, max_length=2_000_000)
