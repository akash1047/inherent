"""Advanced logic tests for Weaviate service."""

from unittest.mock import MagicMock

import pytest
from weaviate.classes.tenants import TenantActivityStatus

from src.config.settings import Settings
from src.services.weaviate import WeaviateService


class TestWeaviateLogic:
    @pytest.fixture
    def mock_settings(self):
        settings = MagicMock(spec=Settings)
        settings.weaviate_url = "http://localhost:8080"
        return settings

    @pytest.fixture
    def weaviate_service(self, mock_settings):
        service = WeaviateService(mock_settings)
        service.client = MagicMock()
        service.client.is_ready.return_value = True
        return service

    @pytest.mark.asyncio
    async def test_ensure_workspace_collection_race_condition(self, weaviate_service):
        """Test race condition handling in ensure_workspace_collection."""
        weaviate_service.client.collections.exists.return_value = False
        # Raise exception that it already exists during create
        weaviate_service.client.collections.create.side_effect = Exception("already exists")

        result = await weaviate_service.ensure_workspace_collection("ws1")

        assert result == "Workspace_ws1"
        assert "Workspace_ws1" in weaviate_service._collection_cache

    @pytest.mark.asyncio
    async def test_ensure_user_tenant_cached(self, weaviate_service):
        """Test tenant retrieval from cache."""
        weaviate_service._tenant_cache["Workspace_ws1"] = {"User_u1"}

        result = await weaviate_service.ensure_user_tenant("ws1", "u1")

        assert result == "User_u1"
        weaviate_service.client.collections.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_user_tenant_exists_active(self, weaviate_service):
        """Test ensuring existing active tenant."""
        mock_collection = MagicMock()
        weaviate_service.client.collections.get.return_value = mock_collection

        mock_tenant = MagicMock()
        mock_tenant.name = "User_u1"
        mock_tenant.activity_status = TenantActivityStatus.ACTIVE
        mock_collection.tenants.get.return_value = {"User_u1": mock_tenant}

        result = await weaviate_service.ensure_user_tenant("ws1", "u1")

        assert result == "User_u1"
        mock_collection.tenants.update.assert_not_called()
        mock_collection.tenants.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_user_tenant_exists_inactive(self, weaviate_service):
        """Test activating existing inactive tenant."""
        mock_collection = MagicMock()
        weaviate_service.client.collections.get.return_value = mock_collection

        mock_tenant = MagicMock()
        mock_tenant.name = "User_u1"
        mock_tenant.activity_status = TenantActivityStatus.INACTIVE
        mock_collection.tenants.get.return_value = {"User_u1": mock_tenant}

        result = await weaviate_service.ensure_user_tenant("ws1", "u1")

        assert result == "User_u1"
        mock_collection.tenants.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_user_tenant_race_condition(self, weaviate_service):
        """Test race condition handling in ensure_user_tenant."""
        mock_collection = MagicMock()
        weaviate_service.client.collections.get.return_value = mock_collection
        mock_collection.tenants.get.return_value = {}

        # Raise exception that it already exists during create
        mock_collection.tenants.create.side_effect = Exception("already exists")

        result = await weaviate_service.ensure_user_tenant("ws1", "u1")

        assert result == "User_u1"
        assert "User_u1" in weaviate_service._tenant_cache["Workspace_ws1"]

    def test_list_workspace_collections_error(self, weaviate_service):
        """Test error handling in list_workspace_collections."""
        weaviate_service.client.collections.list_all.side_effect = Exception("Error")

        result = weaviate_service.list_workspace_collections()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_tenant_stats_error(self, weaviate_service):
        """Test error handling in get_tenant_stats."""
        weaviate_service.client.collections.get.side_effect = Exception("Error")

        result = await weaviate_service.get_tenant_stats("ws1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_delete_workspace_collection_missing(self, weaviate_service):
        """Test delete missing workspace collection."""
        weaviate_service.client.collections.exists.return_value = False

        result = await weaviate_service.delete_workspace_collection("ws1")
        assert result is False
