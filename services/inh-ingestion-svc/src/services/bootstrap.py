"""Seed the principal required by a checkout-free release stack.

This ports the two identity-store upserts from ``scripts/dev/bootstrap.sh``.
It intentionally seeds one principal: the script's second principal remains a
local contributor-only tenancy fixture and must never reach adopter stacks.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import psycopg2
import structlog
from motor.motor_asyncio import AsyncIOMotorClient

from src.config.settings import Settings

logger = structlog.get_logger(__name__)

_PERMISSIONS = ["read", "write", "search"]
_UPSERT_API_KEY = """
INSERT INTO api_keys
    (key_id, key_hash, key_prefix, user_id, workspace_id, name,
     status, permissions, rate_limit)
VALUES (%s, %s, %s, %s, %s, %s, 'active', %s::jsonb, %s)
ON CONFLICT (key_hash) DO UPDATE
SET status = 'active',
    user_id = EXCLUDED.user_id,
    workspace_id = EXCLUDED.workspace_id,
    permissions = EXCLUDED.permissions;
"""


async def run_bootstrap(settings: Settings) -> None:
    """Idempotently seed one API key and its owned workspace."""
    api_key = settings.bootstrap_api_key
    workspace_id = settings.bootstrap_workspace_id
    user_id = settings.bootstrap_user_id

    # The public API rejects every other prefix. Validate all bootstrap input
    # before opening either store so malformed configuration cannot partly seed.
    if not api_key or not api_key.startswith("ink_"):
        raise ValueError("BOOTSTRAP_API_KEY must start with 'ink_'")
    if not workspace_id or not user_id:
        raise ValueError("BOOTSTRAP_WORKSPACE_ID and BOOTSTRAP_USER_ID must be set")

    key_prefix = api_key[:12]
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    # Mint every attempted insert's id. The conflict arbiter is key_hash, while
    # key_id is independently UNIQUE; reusing a fixed id would break rotation.
    with psycopg2.connect(settings.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _UPSERT_API_KEY,
                (
                    str(uuid4()),
                    key_hash,
                    key_prefix,
                    user_id,
                    workspace_id,
                    settings.bootstrap_key_name,
                    json.dumps(_PERMISSIONS),
                    1000,
                ),
            )

    client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongodb_uri)
    try:
        # Ownership lookup returns str(_id), so the document id is the workspace
        # id itself rather than a separate generated Mongo ObjectId.
        await client[settings.mongodb_db_name].workspaces.update_one(
            {"_id": workspace_id},
            {
                "$set": {
                    "user_id": user_id,
                    "name": settings.bootstrap_workspace_name,
                }
            },
            upsert=True,
        )
    finally:
        client.close()

    # This reaches CI and user logs: emit only the display-safe prefix.
    logger.info("Bootstrap principal ready", key_prefix=key_prefix, workspace_id=workspace_id)
