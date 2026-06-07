"""Tests for the auto-restart-after-reset UX fix."""
import pytest
from unittest.mock import AsyncMock, patch

# Match the pattern used by tests/test_api_integration.py: the FastAPI
# TestClient depends on httpx (or the new httpx2 fork), which isn't in
# our minimal CI runner's install. Skip cleanly when it's missing
# instead of failing collection.
httpx = pytest.importorskip("httpx", reason="httpx not installed (needed for FastAPI TestClient)")
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


def test_reset_auto_restarts_bot(client):
    """POST /api/reset must restart the background loops, not leave
    them stopped (Start button dead after Reset)."""
    with patch('main.start_bot', new=AsyncMock(return_value={'status': 'started'})) as mock_start:
        r = client.post('/api/reset')
        assert r.status_code == 200
        body = r.json()
        assert body['status'] == 'reset'
        # start_bot must have been called
        assert mock_start.called
