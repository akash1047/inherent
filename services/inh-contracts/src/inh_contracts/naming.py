"""Weaviate naming — the SINGLE source of truth (#12).

Both the ingestion service and the public API derive Weaviate collection and
tenant names from raw workspace/user ids. The two services MUST agree
byte-for-byte or search will query the wrong collection/tenant.

Golden behavior (anti-drift, asserted by both services' contract tests):
- ws_local_001    -> Workspace_wslocal001
- ws-123          -> Workspace_ws123
- local-dev-user  -> User_localdevuser
- user_001        -> User_user001
"""

import re

# Multi-tenant naming prefixes.
WORKSPACE_COLLECTION_PREFIX = "Workspace_"
USER_TENANT_PREFIX = "User_"


def get_workspace_collection_name(workspace_id: str) -> str:
    """Generate a valid Weaviate collection name from workspace ID.

    Weaviate collection names must:
    - Start with an uppercase letter
    - Only contain alphanumeric characters and underscores
    """
    # Remove any non-alphanumeric characters from workspace_id
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", workspace_id)
    return f"{WORKSPACE_COLLECTION_PREFIX}{safe_id}"


def get_user_tenant_name(user_id: str) -> str:
    """Generate a valid Weaviate tenant name from user ID."""
    # Remove any non-alphanumeric characters from user_id
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", user_id)
    return f"{USER_TENANT_PREFIX}{safe_id}"
