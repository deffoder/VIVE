# VIVE Backend

FastAPI service implementing the contract in
[`../docs/API_SPEC.md`](../docs/API_SPEC.md).

> **Every analyzer in this build is a MOCK/DEMO adapter.** Outputs are
> deterministic scripted values, not model inference, and must never be cited
> as accuracy or detection capability. `GET /api/v1/ready` reports the mode per
> adapter, and every packet carries `adapter_mode`.

## Setup

```bash
cd backend && python -m venv .venv && . .venv/Scripts/activate && pip install -e ".[dev]"
```

On macOS or Linux the activate path is `.venv/bin/activate`.

Copy `.env.example` to `.env` and edit. `.env` is git-ignored; never commit
real secrets.

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive API documentation is served at `/docs`, the schema at
`/openapi.json`.

## Test

```bash
pytest -q
```

## Layout

```text
app/
├── main.py            application factory, middleware, error handlers
├── core/              config, logging, errors, ids, session manager
├── api/routes/        REST endpoints
├── ws/                WebSocket protocol, connection manager, stream endpoint
├── schemas/           Pydantic wire models - the contract source of truth
├── adapters/          model-service interfaces + mock adapters
├── risk/              fusion, temporal risk, policy
└── store/             in-memory event store
```

## Design notes

**Analyzers are reached only through `adapters/interfaces.py`.** Swapping a
mock for a real checkpoint is a configuration change; nothing in routes, fusion
or transport moves.

**Fusion is noisy-OR, not a weighted average.** An average lets a low signal
cancel a high one, so benign anti-spoof evidence would suppress a clear OTP
request. Strong evidence in any channel must be able to raise risk on its own.

**Risk score and confidence are separate.** Confidence reflects how much
evidence supports the assessment and is never a fraud probability. Poor audio
lowers confidence without raising risk.

**Sequencing survives reconnects.** The WebSocket sequence counter lives on the
session, not the socket, so a client that reconnects reads the latest `seq` and
backfills with `GET /api/v1/sessions/{id}/packets?since_seq=`.

**Storage is in-memory.** Audio and transcripts never touch disk
(`../docs/SECURITY_SPEC.md` §4). The engine choice is tracked as O4 in
`../docs/BLOCKERS.md`.
