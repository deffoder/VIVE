"""WebSocket connection registry and sequencing.

Holds one sequence counter per session so frames are ordered across
reconnects: the counter lives with the session, not the socket, which is what
lets a reconnecting client ask for `since_seq` and receive exactly what it
missed.

Only one live socket per session is kept. A second connection for the same
session supersedes the first, which is the reconnect case - the old socket is
closed rather than left to leak.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from app.ws.protocol import ServerFrame, ServerFrameType


@dataclass
class Connection:
    websocket: WebSocket
    session_id: str
    paused: bool = False
    last_client_message: float = 0.0


@dataclass
class SessionChannel:
    seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    connection: Connection | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    def __init__(self) -> None:
        self._channels: dict[str, SessionChannel] = {}

    def channel(self, session_id: str) -> SessionChannel:
        return self._channels.setdefault(session_id, SessionChannel())

    def next_seq(self, session_id: str) -> int:
        return next(self.channel(session_id).seq)

    async def connect(self, session_id: str, websocket: WebSocket) -> Connection:
        channel = self.channel(session_id)
        previous = channel.connection
        if previous is not None:
            # Supersede the stale socket; the client is reconnecting.
            try:
                await previous.websocket.close(code=1012, reason="superseded")
            except Exception:
                pass
        connection = Connection(websocket=websocket, session_id=session_id)
        channel.connection = connection
        return connection

    def disconnect(self, session_id: str, connection: Connection) -> None:
        channel = self._channels.get(session_id)
        if channel is not None and channel.connection is connection:
            channel.connection = None

    async def send(
        self,
        session_id: str,
        frame_type: ServerFrameType,
        data: dict[str, Any] | None = None,
    ) -> int:
        """Sends one frame and returns the sequence number used.

        The seq is allocated even when no socket is attached, so numbering
        stays monotonic across a disconnect.
        """
        seq = self.next_seq(session_id)
        channel = self.channel(session_id)
        connection = channel.connection
        if connection is None:
            return seq
        frame = ServerFrame(
            type=frame_type,
            session_id=session_id,
            seq=seq,
            data=data or {},
        )
        async with channel.lock:
            try:
                await connection.websocket.send_text(frame.model_dump_json())
            except Exception:
                self.disconnect(session_id, connection)
        return seq

    def is_connected(self, session_id: str) -> bool:
        channel = self._channels.get(session_id)
        return channel is not None and channel.connection is not None

    def reset(self) -> None:
        """Demo reset / test seam."""
        self._channels.clear()
