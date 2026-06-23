"""inh-contracts: shared contracts consumed by both Inherent services.

Single source of truth for Weaviate naming (#12) and the versioned cross-service
event schemas (#17). See ``inh_contracts.naming`` and ``inh_contracts.events``.
"""

from inh_contracts.events import (
    CONTRACT_VERSION,
    DocumentCompletionMessage,
    DocumentUploadMessage,
    StorageBackend,
)
from inh_contracts.naming import (
    USER_TENANT_PREFIX,
    WORKSPACE_COLLECTION_PREFIX,
    get_user_tenant_name,
    get_workspace_collection_name,
)

__all__ = [
    "CONTRACT_VERSION",
    "DocumentUploadMessage",
    "DocumentCompletionMessage",
    "StorageBackend",
    "get_workspace_collection_name",
    "get_user_tenant_name",
    "WORKSPACE_COLLECTION_PREFIX",
    "USER_TENANT_PREFIX",
]
