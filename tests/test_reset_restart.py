"""Tests for the auto-restart-after-reset UX fix."""
import pytest
from unittest.mock import AsyncMock, patch
from main import app
from fastapi.testclient import TestClient


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
        # Message reflects auto-restart. We don't pin the exact
        # wording because the original message is localized
        # ("sıfırlandı") and we don't want this test to break every
        # time the user rewords the response. We just assert the
        # response status and that start_bot was awaited.
        assert body['status'] == 'reset'
