"""Session, packet, risk, transcript and report routes.

Paths follow docs/API_SPEC.md 3. `/events` is provided alongside `/packets`
because the external phase prompt names it; both return the same packet list,
which is the event history for a session.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import (
    AuthDep,
    SessionsDep,
    StateDep,
    StoreDep,
    claim_ownership,
    require_owned,
)
from app.core.security import AuditEvent, audit
from app.core.config import API_PREFIX
from app.core.errors import packet_not_found
from app.schemas.models import (
    Alert,
    CreateSessionRequest,
    CreateSessionResponse,
    Packet,
    RiskSummary,
    Session,
    SessionContext,
    TranscriptLine,
)

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a session",
)
async def create_session(
    request: CreateSessionRequest,
    sessions: SessionsDep,
    state: StateDep,
    principal: AuthDep,
) -> CreateSessionResponse:
    # Session creation is limited separately: it allocates state, so it is the
    # cheapest endpoint to abuse.
    if not state.create_limiter.allow(principal.principal_id):
        from app.core.errors import ErrorCode, ViveError

        audit(AuditEvent.RATE_LIMITED, principal, detail="session create")
        raise ViveError(ErrorCode.RATE_LIMITED, "Too many sessions created. Slow down.")

    session = sessions.create(request)
    claim_ownership(state, session.session_id, principal)
    audit(AuditEvent.SESSION_CREATED, principal, session.session_id)
    return CreateSessionResponse(
        session_id=session.session_id,
        status=session.status,
        stream_path=f"{API_PREFIX}/sessions/{session.session_id}/stream",
        expires_in=3600,
    )


@router.get("/sessions", response_model=list[Session], summary="List sessions")
async def list_sessions(
    store: StoreDep,
    principal: AuthDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[Session]:
    return store.list_sessions(limit=limit, offset=offset)


@router.get("/sessions/{session_id}", response_model=Session, summary="Session state")
async def get_session(
    session_id: str, sessions: SessionsDep, state: StateDep, principal: AuthDep
) -> Session:
    require_owned(state, session_id, principal)
    return sessions.get(session_id)


@router.post("/sessions/{session_id}/end", response_model=Session, summary="End a session")
async def end_session(
    session_id: str, sessions: SessionsDep, state: StateDep, principal: AuthDep
) -> Session:
    require_owned(state, session_id, principal)
    ended = sessions.end(session_id)
    audit(AuditEvent.SESSION_ENDED, principal, session_id)
    return ended


@router.post(
    "/sessions/{session_id}/context",
    response_model=Session,
    summary="Set authorized context signals",
)
async def set_context(
    session_id: str,
    context: SessionContext,
    sessions: SessionsDep,
    state: StateDep,
    principal: AuthDep,
) -> Session:
    require_owned(state, session_id, principal)
    return sessions.set_context(session_id, context)


@router.get(
    "/sessions/{session_id}/risk",
    response_model=RiskSummary,
    summary="Current aggregate risk",
)
async def get_risk(
    session_id: str, sessions: SessionsDep, state: StateDep, principal: AuthDep
) -> RiskSummary:
    require_owned(state, session_id, principal)
    session = sessions.get(session_id)
    from app.schemas.models import RiskLevel

    return session.current_risk or RiskSummary(
        score=0, level=RiskLevel.LOW, confidence=0.0
    )


@router.get(
    "/sessions/{session_id}/packets",
    response_model=list[Packet],
    summary="Packet list",
)
async def list_packets(
    session_id: str,
    sessions: SessionsDep,
    state: StateDep,
    principal: AuthDep,
    since_seq: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[Packet]:
    require_owned(state, session_id, principal)
    record = sessions.require_record(session_id)
    packets = record.packets
    if since_seq is not None:
        packets = [p for p in packets if (p.seq or 0) > since_seq]
    return packets[:limit]


@router.get(
    "/sessions/{session_id}/events",
    response_model=list[Packet],
    summary="Event history (alias of /packets)",
)
async def list_events(
    session_id: str,
    sessions: SessionsDep,
    state: StateDep,
    principal: AuthDep,
    since_seq: int | None = Query(default=None, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[Packet]:
    return await list_packets(
        session_id, sessions, state, principal, since_seq=since_seq, limit=limit
    )


@router.get(
    "/sessions/{session_id}/packets/{packet_id}",
    response_model=Packet,
    summary="Single packet",
)
async def get_packet(
    session_id: str,
    packet_id: str,
    sessions: SessionsDep,
    state: StateDep,
    principal: AuthDep,
) -> Packet:
    require_owned(state, session_id, principal)
    record = sessions.require_record(session_id)
    for packet in record.packets:
        if packet.packet_id == packet_id:
            return packet
    raise packet_not_found(packet_id)


@router.get(
    "/sessions/{session_id}/transcript",
    response_model=list[TranscriptLine],
    summary="Ordered transcript",
)
async def get_transcript(
    session_id: str, sessions: SessionsDep, state: StateDep, principal: AuthDep
) -> list[TranscriptLine]:
    require_owned(state, session_id, principal)
    return sessions.require_record(session_id).transcript


@router.get("/sessions/{session_id}/report", summary="Final call report")
async def get_report(
    session_id: str, sessions: SessionsDep, state: StateDep, principal: AuthDep
) -> dict:
    require_owned(state, session_id, principal)
    record = sessions.require_record(session_id)
    session = record.session
    return {
        "session": session.model_dump(),
        "packets_processed": len(record.packets),
        "alerts": [a.model_dump() for a in record.alerts],
        "timings": session.timings.model_dump(),
        "evidence_summary": record.packets[-1].risk.reasons if record.packets else [],
    }


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a session and everything derived from it",
)
async def delete_session(
    session_id: str, sessions: SessionsDep, state: StateDep, principal: AuthDep
) -> None:
    require_owned(state, session_id, principal)
    sessions.require_record(session_id)
    # Real deletion: the record and everything derived from it are removed.
    sessions.delete(session_id)
    state.owners.pop(session_id, None)
    audit(AuditEvent.SESSION_DELETED, principal, session_id)


@router.get("/alerts", response_model=list[Alert], summary="List alerts")
async def list_alerts(
    store: StoreDep,
    principal: AuthDep,
    session_id: str | None = Query(default=None),
    level: str | None = Query(default=None),
) -> list[Alert]:
    alerts = store.all_alerts()
    if session_id:
        alerts = [a for a in alerts if a.session_id == session_id]
    if level:
        alerts = [a for a in alerts if a.level.value.lower() == level.lower()]
    return alerts


@router.post("/alerts/{alert_id}/ack", response_model=Alert, summary="Acknowledge an alert")
async def acknowledge_alert(alert_id: str, store: StoreDep, principal: AuthDep) -> Alert:
    from app.core.errors import ErrorCode, ViveError

    found = store.find_alert(alert_id)
    if found is None:
        raise ViveError(ErrorCode.SESSION_NOT_FOUND, f"No alert with id {alert_id}.")
    session_id, alert = found
    updated = alert.model_copy(update={"acknowledged": True})
    store.replace_alert(session_id, updated)
    return updated
