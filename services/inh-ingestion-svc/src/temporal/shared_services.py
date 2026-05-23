"""Process-level service registry for Temporal activity connections.

Instead of each activity creating and destroying its own DB engine +
connection pool, all activities share long-lived pools from this registry.
The worker initializes the registry at startup and tears it down on shutdown.

Thread safety: Temporal runs async activities in the event loop, so
concurrent initialization is not a concern. A threading lock is included
as a safety net for potential future sync activity executors.

Connection health: All SQLAlchemy engines use pool_pre_ping=True, which
automatically replaces stale connections before use.
"""

import threading

import structlog

from src.config.settings import Settings

logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_settings: Settings | None = None


# Service instances (lazily connected on first access)
_db_service = None
_staging_service = None
_storage_service = None
_weaviate_service = None


def initialize(settings: Settings) -> None:
    """Store settings for lazy service creation. Called once at worker startup."""
    global _settings
    _settings = settings
    logger.info("Shared service registry initialized")


def shutdown() -> None:
    """Disconnect all shared services. Called on worker shutdown."""
    global _db_service, _staging_service
    global _storage_service, _weaviate_service, _settings

    services = [
        ("db", _db_service),
        ("staging", _staging_service),
        ("storage", _storage_service),
        ("weaviate", _weaviate_service),
    ]

    for name, svc in services:
        if svc is not None:
            try:
                svc.disconnect()
            except Exception as e:
                logger.warning(f"Error disconnecting shared {name} service", error=str(e))

    _db_service = None
    _staging_service = None
    _storage_service = None
    _weaviate_service = None
    _settings = None
    logger.info("Shared service registry shutdown")


def _get_settings() -> Settings:
    if _settings is not None:
        return _settings
    from src.config.settings import get_settings

    return get_settings()


def get_db_service():
    """Get or create shared DatabaseService."""
    global _db_service
    if _db_service is None:
        with _lock:
            if _db_service is None:
                from src.services.database import DatabaseService

                _db_service = DatabaseService(_get_settings())
                _db_service.connect()
                logger.debug("Shared DatabaseService connected")
    return _db_service


def get_staging_service():
    """Get or create shared StagingService."""
    global _staging_service
    if _staging_service is None:
        with _lock:
            if _staging_service is None:
                from src.services.staging import StagingService

                _staging_service = StagingService(_get_settings())
                _staging_service.connect()
                logger.debug("Shared StagingService connected")
    return _staging_service


def get_storage_service():
    """Get or create shared StorageService."""
    global _storage_service
    if _storage_service is None:
        with _lock:
            if _storage_service is None:
                from src.services.storage import StorageService

                _storage_service = StorageService(_get_settings())
                _storage_service.connect()
                logger.debug("Shared StorageService connected")
    return _storage_service


def get_weaviate_service():
    """Get or create shared WeaviateService.

    Returns None if Weaviate is not available (non-critical service).
    """
    global _weaviate_service
    if _weaviate_service is None:
        with _lock:
            if _weaviate_service is None:
                from src.services.weaviate import WeaviateService

                svc = WeaviateService(_get_settings())
                try:
                    svc.connect()
                    _weaviate_service = svc
                    logger.debug("Shared WeaviateService connected")
                except Exception as e:
                    logger.warning("Weaviate not available for shared service", error=str(e))
                    return None
    return _weaviate_service
