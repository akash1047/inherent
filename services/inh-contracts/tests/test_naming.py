"""Golden naming tests — the package is the source of truth (#12)."""

import pytest

from inh_contracts import CONTRACT_VERSION
from inh_contracts.naming import get_user_tenant_name, get_workspace_collection_name


@pytest.mark.parametrize(
    ("workspace_id", "expected"),
    [
        ("ws_local_001", "Workspace_wslocal001"),
        ("ws-123", "Workspace_ws123"),
    ],
)
def test_workspace_collection_name_golden(workspace_id: str, expected: str) -> None:
    assert get_workspace_collection_name(workspace_id) == expected


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [
        ("local-dev-user", "User_localdevuser"),
        ("user_001", "User_user001"),
    ],
)
def test_user_tenant_name_golden(user_id: str, expected: str) -> None:
    assert get_user_tenant_name(user_id) == expected


def test_contract_version_is_pinned() -> None:
    assert CONTRACT_VERSION == "1.0.0"
