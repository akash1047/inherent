"""Read-only Mongo client for control-plane lookups.

public-api-svc owns its own PG api_keys table for auth, but workspace
ownership (and user→workspace membership) is canonically tracked in the
MongoDB ``workspaces`` and ``users`` collections owned by inh-intg-svc.

This client is **read-only**. We never write here. All writes to control-
plane data continue to flow through intg-svc.

The client is lazy-loaded on first use and reused for the process
lifetime — same pattern as inh-ingestion-svc/src/services/audit_mongo_writer.py.
"""

from __future__ import annotations

import threading

from motor.motor_asyncio import AsyncIOMotorClient

from src.config import settings
from src.utils import get_logger

logger = get_logger(__name__)


_CLIENT_LOCK = threading.Lock()
_CLIENT: AsyncIOMotorClient | None = None
_CLIENT_URI: str | None = None


def get_mongo_client() -> AsyncIOMotorClient:
    """Return a process-singleton AsyncIOMotorClient pointed at MONGODB_URI."""
    global _CLIENT, _CLIENT_URI
    uri = settings.mongodb_uri
    if _CLIENT is None or _CLIENT_URI != uri:
        with _CLIENT_LOCK:
            if _CLIENT is None or _CLIENT_URI != uri:
                if _CLIENT is not None:
                    try:
                        _CLIENT.close()
                    except Exception:
                        pass
                logger.info("mongo_client_initialized", uri_host=uri.split("@")[-1])
                _CLIENT = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
                _CLIENT_URI = uri
    return _CLIENT


async def close_mongo_client() -> None:
    """Close the singleton — call from FastAPI lifespan shutdown."""
    global _CLIENT
    if _CLIENT is not None:
        try:
            _CLIENT.close()
        except Exception:
            pass
        _CLIENT = None
