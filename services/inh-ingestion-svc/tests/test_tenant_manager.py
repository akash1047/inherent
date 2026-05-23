"""Tests for TenantManager service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.config.settings import Settings
from src.services.database import DatabaseService
from src.services.tenant_manager import TenantManager
from src.services.weaviate import WeaviateService


class TestTenantManagerExtended:
    """Additional tests for TenantManager."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock(spec=Settings)
        settings.auto_create_tenants = True
        return settings

    @pytest.fixture
    def mock_db_service(self):
        """Create mock database service."""
        db_service = MagicMock(spec=DatabaseService)
        db_service.get_idle_tenants = AsyncMock(return_value=[])
        db_service.get_user_workspaces = AsyncMock(return_value=[])
        db_service.update_tenant_status = AsyncMock(return_value=True)
        db_service.delete_workspace_data = AsyncMock(return_value=5)
        db_service.get_tenant = AsyncMock(return_value={"user_id": "user1"})
        db_service.get_workspace_metadata = AsyncMock(return_value={"workspace_id": "ws1"})
        return db_service

    @pytest.fixture
    def mock_weaviate_service(self):
        """Create mock Weaviate service."""
        weaviate_service = MagicMock(spec=WeaviateService)
        weaviate_service.deactivate_user_tenant = AsyncMock(return_value=True)
        weaviate_service.delete_workspace_collection = AsyncMock(return_value=True)
        weaviate_service.get_tenant_stats = AsyncMock(return_value={})
        return weaviate_service

    @pytest.fixture
    def tenant_manager(self, mock_settings, mock_db_service, mock_weaviate_service):
        """Create TenantManager instance."""
        return TenantManager(
            settings=mock_settings,
            db_service=mock_db_service,
            weaviate_service=mock_weaviate_service,
        )

    def test_set_services(self, tenant_manager):
        """Test setting services."""
        new_db = MagicMock()
        new_weaviate = MagicMock()

        tenant_manager.set_services(db_service=new_db, weaviate_service=new_weaviate)

        assert tenant_manager.db_service == new_db
        assert tenant_manager.weaviate_service == new_weaviate

    @pytest.mark.asyncio
    async def test_ensure_workspace_metadata(self, tenant_manager, mock_db_service):
        """Test ensuring workspace metadata."""
        workspace_id = "ws1"
        user_id = "user1"
        mock_db_service.upsert_workspace_metadata.return_value = 1

        await tenant_manager.ensure_workspace_metadata(workspace_id, user_id)

        mock_db_service.upsert_workspace_metadata.assert_called_with(
            workspace_id=workspace_id, user_id=user_id
        )

    @pytest.mark.asyncio
    async def test_deactivate_idle_tenants(
        self, tenant_manager, mock_db_service, mock_weaviate_service
    ):
        """Test deactivating idle tenants."""
        # Setup mock data
        mock_db_service.get_idle_tenants.return_value = [{"user_id": "user1"}]
        mock_db_service.get_user_workspaces.return_value = [{"workspace_id": "ws1"}]

        count = await tenant_manager.deactivate_idle_tenants(idle_days=30)

        assert count == 1
        mock_db_service.get_idle_tenants.assert_called_once()
        mock_db_service.get_user_workspaces.assert_called_with("user1")
        mock_weaviate_service.deactivate_user_tenant.assert_called_with(
            workspace_id="ws1", user_id="user1"
        )
        mock_db_service.update_tenant_status.assert_called_with("user1", "inactive")

    @pytest.mark.asyncio
    async def test_reactivate_tenant(self, tenant_manager, mock_db_service):
        """Test reactivating a tenant."""
        user_id = "user1"

        result = await tenant_manager.reactivate_tenant(user_id)

        assert result is True
        mock_db_service.update_tenant_status.assert_called_with(user_id, "active")

    @pytest.mark.asyncio
    async def test_delete_workspace(self, tenant_manager, mock_db_service, mock_weaviate_service):
        """Test deleting a workspace."""
        workspace_id = "ws1"
        tenant_manager._workspace_cache.add(f"{workspace_id}:user1")

        result = await tenant_manager.delete_workspace(workspace_id)

        assert result is True
        mock_weaviate_service.delete_workspace_collection.assert_called_with(workspace_id)
        mock_db_service.delete_workspace_data.assert_called_with(workspace_id)
        # Verify cache cleared
        assert f"{workspace_id}:user1" not in tenant_manager._workspace_cache

    @pytest.mark.asyncio
    async def test_get_tenant_info(self, tenant_manager, mock_db_service):
        """Test getting tenant info."""
        user_id = "user1"

        info = await tenant_manager.get_tenant_info(user_id)

        assert info == {"user_id": "user1"}
        mock_db_service.get_tenant.assert_called_with(user_id)

    @pytest.mark.asyncio
    async def test_get_workspace_info(self, tenant_manager, mock_db_service):
        """Test getting workspace info."""
        workspace_id = "ws1"

        info = await tenant_manager.get_workspace_info(workspace_id)

        assert info == {"workspace_id": "ws1"}
        mock_db_service.get_workspace_metadata.assert_called_with(workspace_id)
