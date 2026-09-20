"""WebSocket streaming endpoint.

`WS /api/v1/sessions/{session_id}/stream` (docs/API_SPEC.md 6).

Connection lifecycle:
  accept -> authenticate -> validate session -> send session.state
  -> receive loop (audio / control frames, idle-timeout guarded)
  -> clean close

Reconnect safety: the sequence counter lives on the session, not the socket, so
after a reconnect the client reads the latest `seq` and backfills anything it
missed with `GET .../packets?since_seq=`. Nothing is silently dropped.

Auth: the token may arrive as a query parameter or in the first frame, because
browsers cannot set headers on a WebSocket handshake.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import AppState
from app.core.config import get_settings
from app.core.errors import ErrorCode, ViveError
from app.core.logging import get_logger
from app.schemas.models import SessionStatus
from app.ws.protocol import ClientFrame, ClientFrameType, ServerFrameType

router = APIRouter()
log = get_logger("vive.ws")

CLOSE_UNAUTHORIZED = 4401
CLOSE_NOT_FOUND = 4404
CLOSE_SESSION_ENDED = 4409
CLOSE_INVALID = 4400


@router.websocket("/sessions/{session_id}/stream")
async def stream(websocket: WebSocket, session_id: str) -> None:
    state: AppState = websocket.app.state.vive
    settings = get_settings()

    await websocket.accept()

    # --- authentication -------------------------------------------------
    if settings.auth_enforced:
        token = websocket.query_params.get("token")
        if token is None:
            header = websocket.headers.get("authorization", "")
            parts = header.split(None, 1)
            token = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else None
        if token not in settings.tokens:
            await _send_error(websocket, ErrorCode.UNAUTHENTICATED, "Valid token required.")
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return

    # --- session validation ---------------------------------------------
    record = state.store.get(session_id)
    if record is None:
        await _send_error(websocket, ErrorCode.SESSION_NOT_FOUND, f"No session {session_id}.")
        await websocket.close(code=CLOSE_NOT_FOUND)
        return
    if record.session.status == SessionStatus.ENDED:
        await _send_error(
            websocket, ErrorCode.SESSION_ALREADY_ENDED, f"Session {session_id} has ended."
        )
        await websocket.close(code=CLOSE_SESSION_ENDED)
        return

    connection = await state.connections.connect(session_id, websocket)
    state.sessions.mark_streaming(session_id)
    log.info("ws connected", extra={"session_id": session_id, "event": "ws.connect"})

    await state.connections.send(
        session_id,
        ServerFrameType.SESSION_STATE,
        record.session.model_dump(mode="json"),
    )

    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=settings.ws_idle_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # Idle past the timeout: send one heartbeat, then give up if
                # the peer still says nothing on the next cycle.
                await state.connections.send(
                    session_id, ServerFrameType.HEARTBEAT, {"idle": True}
                )
                continue

            if message.get("type") == "websocket.disconnect":
                break

            if (payload := message.get("bytes")) is not None:
                if len(payload) > settings.max_audio_frame_bytes:
                    await _send_error(
                        websocket, ErrorCode.VALIDATION_ERROR, "Audio frame too large."
                    )
                    continue
                if not connection.paused:
                    await _process(state, session_id, pcm=payload)
                continue

            text = message.get("text")
            if text is None:
                continue

            try:
                frame = ClientFrame.model_validate_json(text)
            except ValidationError:
                await _send_error(
                    websocket, ErrorCode.VALIDATION_ERROR, "Malformed client frame."
                )
                continue

            if frame.type == ClientFrameType.PAUSE:
                connection.paused = True
            elif frame.type == ClientFrameType.RESUME:
                connection.paused = False
            elif frame.type == ClientFrameType.PONG:
                pass
            elif frame.type == ClientFrameType.END:
                state.sessions.end(session_id)
                await state.connections.send(
                    session_id,
                    ServerFrameType.SESSION_ENDED,
                    state.sessions.get(session_id).model_dump(mode="json"),
                )
                break
            elif frame.type == ClientFrameType.AUDIO:
                if connection.paused:
                    continue
                pcm = b""
                if frame.audio_b64:
                    try:
                        pcm = base64.b64decode(frame.audio_b64, validate=True)
                    except (binascii.Error, ValueError):
                        await _send_error(
                            websocket, ErrorCode.VALIDATION_ERROR, "audio_b64 is not valid base64."
                        )
                        continue
                    if len(pcm) > settings.max_audio_frame_bytes:
                        await _send_error(
                            websocket, ErrorCode.VALIDATION_ERROR, "Audio frame too large."
                        )
                        continue
                await _process(
                    state,
                    session_id,
                    pcm=pcm,
                    transcript_hint=frame.transcript,
                    speaker=frame.speaker or "Caller",
                )

    except WebSocketDisconnect:
        pass
    except ViveError as exc:
        await _send_error(websocket, exc.code, exc.message)
    except Exception:
        log.exception("ws failure", extra={"session_id": session_id, "event": "ws.error"})
        await _send_error(websocket, ErrorCode.INTERNAL_ERROR, "Stream failed.")
    finally:
        state.connections.disconnect(session_id, connection)
        log.info("ws disconnected", extra={"session_id": session_id, "event": "ws.disconnect"})
        try:
            await websocket.close()
        except Exception:
            pass


async def _process(
    state: AppState,
    session_id: str,
    *,
    pcm: bytes = b"",
    transcript_hint: str | None = None,
    speaker: str = "Caller",
) -> None:
    """Run one window and emit the resulting frames."""
    try:
        packet, alert = state.sessions.process_window(
            session_id, pcm=pcm, transcript_hint=transcript_hint, speaker=speaker
        )
    except ViveError as exc:
        channel = state.connections.channel(session_id)
        if channel.connection is not None:
            await _send_error(channel.connection.websocket, exc.code, exc.message)
        return

    await state.connections.send(
        session_id, ServerFrameType.PACKET_NEW, packet.model_dump(mode="json")
    )

    session = state.sessions.get(session_id)
    await state.connections.send(
        session_id,
        ServerFrameType.RISK_UPDATE,
        {
            "current_risk": session.current_risk.model_dump() if session.current_risk else None,
            "overall_risk": session.overall_risk.model_dump() if session.overall_risk else None,
            "timings": session.timings.model_dump(),
            "packets_processed": session.packets_processed,
            "duration_sec": session.duration_sec,
        },
    )

    if packet.asr.transcript:
        await state.connections.send(
            session_id,
            ServerFrameType.TRANSCRIPT_APPEND,
            {
                "packet_id": packet.packet_id,
                "speaker": speaker,
                "text": packet.asr.transcript,
                "language": packet.language,
                "confidence": packet.asr.confidence,
            },
        )

    if alert is not None:
        await state.connections.send(
            session_id, ServerFrameType.ALERT_RAISED, alert.model_dump(mode="json")
        )


async def _send_error(websocket: WebSocket, code: ErrorCode, message: str) -> None:
    """Errors carry a code and a safe message - never a stack trace."""
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": ServerFrameType.ERROR.value,
                    "session_id": "",
                    "seq": 0,
                    "data": {"code": code.value, "message": message},
                }
            )
        )
    except Exception:
        pass
