"""Tests for API key authentication."""

from datetime import datetime, timedelta, timezone

from src.models.api_key import APIKeyInfo


class TestAPIKeyInfo:
    def test_has_permission_true(self):
        key = APIKeyInfo(
            key_id="test",
            user_id="user",
            workspace_id="workspace",
            permissions=["read", "search"],
        )
        assert key.has_permission("read") is True
        assert key.has_permission("search") is True

    def test_has_permission_false(self):
        key = APIKeyInfo(
            key_id="test",
            user_id="user",
            workspace_id="workspace",
            permissions=["read"],
        )
        assert key.has_permission("write") is False

    def test_is_expired_false_when_no_expiry(self):
        key = APIKeyInfo(
            key_id="test",
            user_id="user",
            workspace_id="workspace",
            expires_at=None,
        )
        assert key.is_expired() is False

    def test_is_expired_false_when_future(self):
        key = APIKeyInfo(
            key_id="test",
            user_id="user",
            workspace_id="workspace",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
        assert key.is_expired() is False

    def test_is_expired_true_when_past(self):
        key = APIKeyInfo(
            key_id="test",
            user_id="user",
            workspace_id="workspace",
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert key.is_expired() is True
