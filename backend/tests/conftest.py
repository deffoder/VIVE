"""Shared test fixtures."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("VIVE_ENV", "development")
os.environ.setdefault("VIVE_API_TOKENS", "")
os.environ.setdefault("VIVE_WS_IDLE_TIMEOUT_SECONDS", "5")

from app.core import ids  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_ids():
    ids.reset_for_tests()
    yield


@pytest.fixture
def client() -> TestClient:
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def session_id(client: TestClient) -> str:
    response = client.post(
        "/api/v1/sessions",
        json={"source_type": "VOIP", "language": "auto"},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


def ws_send(ws, transcript: str, speaker: str = "Caller") -> None:
    ws.send_json({"type": "client.audio", "transcript": transcript, "speaker": speaker})


def drain_until(ws, frame_type: str, limit: int = 12) -> dict:
    """Reads frames until one of `frame_type` arrives."""
    for _ in range(limit):
        frame = ws.receive_json()
        if frame["type"] == frame_type:
            return frame
    raise AssertionError(f"frame {frame_type} not received within {limit} frames")
