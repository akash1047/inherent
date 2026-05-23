"""API key authentication for the ingestion HTTP API.

Uses constant-time comparison (hmac.compare_digest) to prevent
timing side-channel attacks against the secret key.
"""

from __future__ import annotations

import hmac

import structlog
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """Validate the request API key against the configured secret.

    Raises:
        HTTPException: 401 if key is missing, 403 if invalid, 500 if not configured.
    """
    expected = get_settings().ingestion_api_key

    if not expected:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: INGESTION_API_KEY is not set.",
        )

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header.",
        )

    if not hmac.compare_digest(api_key.encode("utf-8"), expected.encode("utf-8")):
        logger.warning("Rejected API key attempt", source_ip="[redacted]")
        raise HTTPException(status_code=403, detail="Invalid API key.")

    return api_key
