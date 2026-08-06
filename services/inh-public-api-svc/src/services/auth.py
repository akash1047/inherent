"""Authentication service for API key validation."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from src.models.api_key import APIKeyInfo
from src.services.database import DatabaseService, get_database
from src.utils import get_logger

logger = get_logger(__name__)


class AuthService:
    """Service for API key authentication."""

    def __init__(self, database: DatabaseService):
        self.database = database

    async def validate_api_key(self, api_key: str) -> APIKeyInfo | None:
        """Validate an API key and return key info if valid."""
        if not api_key:
            return None

        # Clean up the key (remove "Bearer " prefix if present)
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]

        return await self.database.validate_api_key(api_key)

    async def require_api_key(
        self,
        api_key: str,
        required_permission: str | None = None,
    ) -> APIKeyInfo:
        """Validate API key and raise if invalid."""
        key_info = await self.validate_api_key(api_key)

        if not key_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        if key_info.is_expired():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        if required_permission and not key_info.has_permission(required_permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key does not have '{required_permission}' permission",
            )

        return key_info


# Singleton
_auth_service: AuthService | None = None


async def get_auth_service() -> AuthService:
    """Get the auth service instance."""
    global _auth_service
    if _auth_service is None:
        database = await get_database()
        _auth_service = AuthService(database)
    return _auth_service


@dataclass
class ResolvedAuth:
    """API key info with a resolved workspace_id."""

    key_info: APIKeyInfo
    workspace_id: str | None


# FastAPI dependencies
async def get_api_key_info(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> APIKeyInfo:
    """FastAPI dependency to validate API key from headers."""
    # Try X-API-Key header first, then Authorization header
    api_key = x_api_key
    if not api_key and authorization:
        if authorization.startswith("Bearer "):
            api_key = authorization[7:]
        else:
            api_key = authorization

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Provide X-API-Key header or Authorization: Bearer <key>",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    auth_service = await get_auth_service()
    return await auth_service.require_api_key(api_key)


async def get_search_permission(
    key_info: Annotated[APIKeyInfo, Depends(get_api_key_info)],
) -> APIKeyInfo:
    """Require search permission."""
    if not key_info.has_permission("search"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not have 'search' permission",
        )
    return key_info


async def get_read_permission(
    key_info: Annotated[APIKeyInfo, Depends(get_api_key_info)],
) -> APIKeyInfo:
    """Require read permission."""
    if not key_info.has_permission("read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not have 'read' permission",
        )
    return key_info


async def get_write_permission(
    key_info: Annotated[APIKeyInfo, Depends(get_api_key_info)],
) -> APIKeyInfo:
    """Require write permission."""
    if not key_info.has_permission("write"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not have 'write' permission",
        )
    return key_info


async def get_authorized_workspace_ids(
    key_info: APIKeyInfo, database: DatabaseService
) -> list[str]:
    """Return every workspace_id ``key_info`` is authorised to act on.

    This is the SINGLE source of truth for the key-scoping rule (#138),
    shared by REST (``_resolve_workspace`` below) and MCP
    (``src/mcp_server/server.py``) so the two surfaces cannot drift.

    Always consults ``database.get_user_workspace_ids`` — current ownership,
    backed by Mongo (the canonical source, see ``database.py:770``) — even
    for a workspace-scoped key (#138 blocker-2 follow-up). The first #138 cut
    trusted ``key_info.workspace_id`` unconditionally for a scoped key, which
    reopened a narrower hole: the Postgres ``api_keys`` row is not kept in
    sync with Mongo, so if a workspace is deleted or transferred away from
    the key's owner after the key was issued, the stale row's
    ``workspace_id`` / ``status='active'`` never gets revoked and the key
    would still be served that workspace. This costs one extra ownership
    lookup per scoped-key request; correctness here outweighs it (the lookup
    is a single indexed query, not a fan-out).

    - A *workspace-scoped* key (``key_info.workspace_id`` set) is authorised
      for AT MOST that one workspace, and only while its owner still owns
      it — the INTERSECTION of the key's binding and current ownership. If
      the owner no longer owns it, the key is authorised for NOTHING: fail
      closed, never fall back to the user's other workspaces (that fallback
      is exactly the scope-expansion #138 exists to prevent).
    - A *user-scoped* key (``workspace_id is None``) may act on every
      workspace its owning user currently owns.
    """
    owned = await database.get_user_workspace_ids(key_info.user_id)
    if key_info.workspace_id:
        # Truthy, not `is not None`: an empty-string workspace_id (no
        # issuance path produces one today) is treated as unscoped rather
        # than as a binding to "", matching _resolve_workspace's truthiness
        # checks elsewhere in this module (#138 follow-up).
        return [key_info.workspace_id] if key_info.workspace_id in owned else []
    return owned


def describe_workspace_denial(key_info: APIKeyInfo, requested_workspace_id: str) -> str:
    """Return the rejection message for a workspace ``key_info`` is not
    authorised for — the single wording shared by REST (``_resolve_workspace``)
    and every MCP call site that rejects an out-of-scope workspace, so the two
    surfaces (and MCP's own call sites, which previously had two different
    strings of their own) never describe the same rejection three different
    ways (#138 follow-up).

    A workspace-scoped key gets an ACTIONABLE message naming its OWN bound
    workspace: that is the caller's own grant, not the owner's other
    workspaces, so revealing it leaks nothing and lets the caller immediately
    retry with the right id instead of treating the rejection as "workspace
    doesn't exist" and guessing or giving up. A user-scoped key gets the
    generic "you don't have access" message, since there is no one workspace
    to point back to — the caller must consult its own owned set.
    """
    if key_info.workspace_id is not None:
        return (
            f"API key is scoped to workspace '{key_info.workspace_id}' "
            f"and cannot access workspace '{requested_workspace_id}'"
        )
    return f"You don't have access to workspace '{requested_workspace_id}'"


async def _resolve_workspace(
    key_info: APIKeyInfo,
    header_workspace_id: str | None,
    *,
    required: bool = False,
) -> ResolvedAuth:
    """Resolve workspace_id from header or API key, with access validation.

    A *workspace-scoped* key (``key_info.workspace_id`` set) is bound to exactly
    that workspace and may never act on a different one — even one its owning
    user also owns. Honouring an ``X-Workspace-Id`` header that differs from the
    key's binding would collapse the key's scope to "any workspace the user
    owns", defeating the point of issuing a scoped key. Only *user-scoped* keys
    (``workspace_id is None``) may select among the user's workspaces via header.

    Every branch below derives its authorised set from
    ``get_authorized_workspace_ids`` — INCLUDING the scoped-key branch, which
    used to trust ``key_info.workspace_id`` directly without confirming the
    binding is still owned. That was a second, independent implementation of
    the same scoping rule living inline here instead of in the shared
    function, and the two copies had already started to drift (#138
    blocker-2/item-6 follow-up): this collapses them into one.
    """
    database = await get_database()
    authorized = await get_authorized_workspace_ids(key_info, database)

    # Workspace-scoped key: the binding wins, but only while it is still
    # owned — get_authorized_workspace_ids intersects the binding with
    # current ownership, so a stale binding (workspace deleted/transferred
    # away from the key's owner) fails closed here too, not just on MCP.
    if key_info.workspace_id:
        if header_workspace_id is not None and header_workspace_id != key_info.workspace_id:
            logger.warning(
                "workspace_access_denied",
                reason="scoped_key_header_mismatch",
                user_id=key_info.user_id,
                key_id=key_info.key_id,
                key_workspace_id=key_info.workspace_id,
                requested_workspace_id=header_workspace_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=describe_workspace_denial(key_info, header_workspace_id),
            )
        if key_info.workspace_id not in authorized:
            # The header agrees with the binding (or is absent), but the
            # binding itself is stale: get_authorized_workspace_ids found the
            # key's owner no longer owns this workspace. Fail closed instead
            # of serving a workspace the owner has lost — never fall back to
            # whatever else the owner currently owns.
            logger.warning(
                "workspace_access_denied",
                reason="scoped_key_binding_not_owned",
                user_id=key_info.user_id,
                key_id=key_info.key_id,
                key_workspace_id=key_info.workspace_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"API key is scoped to workspace '{key_info.workspace_id}', "
                    "which is no longer accessible"
                ),
            )
        return ResolvedAuth(key_info=key_info, workspace_id=key_info.workspace_id)

    # User-scoped key: a header may select any workspace the user actually owns.
    workspace_id = header_workspace_id
    if workspace_id:
        if workspace_id in authorized:
            return ResolvedAuth(key_info=key_info, workspace_id=workspace_id)
        # Log the attempted vs authorised set so support can tell "user pasted
        # the wrong id (e.g. Clerk org_id / workspace name)" apart from a real
        # ownership gap without shelling into the DB.
        logger.warning(
            "workspace_access_denied",
            reason="requested_workspace_not_in_user_set",
            user_id=key_info.user_id,
            key_id=key_info.key_id,
            requested_workspace_id=workspace_id,
            authorised_workspace_ids=authorized,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=describe_workspace_denial(key_info, workspace_id),
        )

    # No workspace from header or key — try to resolve from the authorised set.
    if required:
        if not authorized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No workspaces found. Provide X-Workspace-Id header.",
            )
        if len(authorized) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Multiple workspaces found. Provide X-Workspace-Id header "
                    "to specify which workspace to use."
                ),
            )
        return ResolvedAuth(key_info=key_info, workspace_id=authorized[0])

    # For read/search — use first workspace if exactly one, else None
    if len(authorized) == 1:
        return ResolvedAuth(key_info=key_info, workspace_id=authorized[0])

    return ResolvedAuth(key_info=key_info, workspace_id=None)


async def resolve_workspace_write(
    key_info: Annotated[APIKeyInfo, Depends(get_write_permission)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> ResolvedAuth:
    """Resolve workspace for write operations (workspace required)."""
    return await _resolve_workspace(key_info, x_workspace_id, required=True)


async def resolve_workspace_read(
    key_info: Annotated[APIKeyInfo, Depends(get_read_permission)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> ResolvedAuth:
    """Resolve workspace for read operations (workspace optional for single-workspace users)."""
    return await _resolve_workspace(key_info, x_workspace_id, required=False)


async def resolve_workspace_search(
    key_info: Annotated[APIKeyInfo, Depends(get_search_permission)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> ResolvedAuth:
    """Resolve workspace for search operations."""
    return await _resolve_workspace(key_info, x_workspace_id, required=False)
