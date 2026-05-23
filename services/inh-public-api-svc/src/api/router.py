"""Main API router."""

from fastapi import APIRouter

from src.api.v1 import chunks, documents, search

router = APIRouter(prefix="/v1")

router.include_router(search.router, tags=["Search"])
router.include_router(documents.router, tags=["Documents"])
router.include_router(chunks.router, tags=["Chunks"])
