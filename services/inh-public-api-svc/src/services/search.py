"""Search service for semantic search operations."""

import json
import re
import time
from typing import Any

import httpx
from inh_contracts.naming import (
    WORKSPACE_COLLECTION_PREFIX,
    get_user_tenant_name,
    get_workspace_collection_name,
)

from src.config import settings
from src.models.search import SearchRequest, SearchResponse, SearchResult
from src.services.database import DatabaseService, get_database
from src.utils import get_logger

logger = get_logger(__name__)

# Re-exported for backward compatibility (the WORKSPACE_COLLECTION_PREFIX
# constant and the naming helpers now live in the shared contracts package).
__all__ = [
    "WORKSPACE_COLLECTION_PREFIX",
    "SearchService",
    "get_search_service",
    "close_search_service",
]


def _get_workspace_collection_name(workspace_id: str) -> str:
    """Return the Weaviate collection name for a workspace.

    Thin wrapper over the shared contracts helper (single source of truth, #12),
    kept under its existing private name so callers and golden tests still work.
    """
    return get_workspace_collection_name(workspace_id)


def _get_user_tenant_name(user_id: str) -> str:
    """Return the Weaviate tenant name for a user.

    Thin wrapper over the shared contracts helper (single source of truth, #12),
    kept under its existing private name so callers and golden tests still work.
    """
    return get_user_tenant_name(user_id)


class SearchService:
    """Service for semantic search operations."""

    def __init__(self, database: DatabaseService, weaviate_url: str):
        self.database = database
        self.weaviate_url = weaviate_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get HTTP client for Weaviate."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.weaviate_url,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except RuntimeError as e:
                # In FastAPI lifespan shutdown (especially under test runners),
                # the event loop may already be closing, and httpx/anyio can
                # raise "Event loop is closed". We treat that as non-fatal.
                if "Event loop is closed" in str(e):
                    logger.warning(
                        "Ignoring event-loop-closed error during search client shutdown",
                        error=str(e),
                    )
                else:
                    raise
            finally:
                self._client = None

    async def is_connected(self) -> bool:
        """Check if Weaviate is reachable."""
        try:
            client = await self._get_client()
            response = await client.get("/v1/.well-known/ready", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    async def search(
        self,
        workspace_id: str,
        user_id: str,
        request: SearchRequest,
    ) -> SearchResponse:
        """Perform search scoped to a workspace and user tenant.

        Dispatches to the Weaviate query shape matching request.search_mode:
        - semantic: nearVector (client-side embedding, 384-dim)
        - hybrid:   hybrid (BM25 + vector with alpha fusion, client-side embedding)
        - keyword:  bm25 (pure keyword)

        Weaviate or network errors propagate to the caller — no silent fallback.
        """
        start_time = time.time()
        results = await self._search_weaviate(workspace_id, user_id, request)
        processing_time = (time.time() - start_time) * 1000
        return SearchResponse(
            results=results,
            query=request.query,
            total_results=len(results),
            processing_time_ms=round(processing_time, 2),
            search_mode=request.search_mode,
        )

    async def _search_weaviate(
        self,
        workspace_id: str,
        user_id: str,
        request: SearchRequest,
    ) -> list[SearchResult]:
        """Execute the requested search mode against a workspace-specific Weaviate collection."""
        client = await self._get_client()

        collection_name = _get_workspace_collection_name(workspace_id)
        tenant_name = _get_user_tenant_name(user_id)

        assert collection_name.replace(
            "_", ""
        ).isalnum(), f"Unsafe collection name: {collection_name}"
        assert tenant_name.replace("_", "").isalnum(), f"Unsafe tenant name: {tenant_name}"

        graphql_query = self._build_graphql(collection_name, tenant_name, request)

        try:
            response = await client.post("/v1/graphql", json=graphql_query)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise exc

        # GraphQL returns 200 even on errors — check for them explicitly
        if data.get("errors"):
            raise httpx.HTTPError(
                f"Weaviate GraphQL error: {data['errors'][0].get('message', 'unknown')}"
            )

        chunks = data.get("data", {}).get("Get", {}).get(collection_name, []) or []

        results: list[SearchResult] = []
        for chunk in chunks:
            additional = chunk.get("_additional", {}) or {}

            # Weaviate score sources differ by query type:
            # - bm25 / hybrid → _additional.score (BM25 ts_rank-style float)
            # - nearVector / nearText → _additional.score is empty; certainty (0..1) is the
            #   normalised similarity. Fall back to certainty so semantic mode surfaces a
            #   non-zero, comparable relevance value to clients.
            def _to_float(value: object) -> float:
                if isinstance(value, (int, float, str)):
                    try:
                        return float(value)
                    except ValueError:
                        return 0.0
                return 0.0

            bm25_score = _to_float(additional.get("score"))
            certainty = _to_float(additional.get("certainty"))
            distance = _to_float(additional.get("distance"))

            if bm25_score > 0:
                score = bm25_score
            elif certainty > 0:
                score = certainty
            elif distance > 0:
                # cosine distance is in [0, 2]; convert to a similarity in [-1, 1] then
                # squash to [0, 1] for a comparable score
                score = max(0.0, 1.0 - (distance / 2.0))
            else:
                score = 0.0

            if score < request.min_score:
                continue
            results.append(
                SearchResult(
                    chunk_id=additional.get("id", ""),
                    document_id=chunk.get("document_id", ""),
                    document_name=chunk.get("original_filename", ""),
                    content=chunk.get("content", ""),
                    score=round(score, 4),
                    metadata={"chunk_index": chunk.get("chunk_index")},
                )
            )
        return results

    def _build_graphql(
        self,
        collection_name: str,
        tenant_name: str,
        request: SearchRequest,
    ) -> dict:
        """Compose the GraphQL query body for the requested search mode."""
        escaped_query = request.query.replace("\\", "\\\\").replace('"', '\\"')
        where_clause = ""
        if request.document_ids:
            where_filter: dict[str, Any] = {
                "path": ["document_id"],
                "operator": "ContainsAny",
                "valueTextArray": request.document_ids,
            }
            where_clause = f"where: {self._format_where(where_filter)}"

        if request.search_mode == "keyword":
            search_args = f'bm25: {{ query: "{escaped_query}" }}'
        else:
            # Semantic and hybrid both need the query vector computed client-side
            # because Weaviate is configured without a text vectorizer module.
            from src.services.embedder import embed_query

            vector_list = list(embed_query(request.query))
            vector_literal = "[" + ", ".join(f"{v:.6f}" for v in vector_list) + "]"
            if request.search_mode == "hybrid":
                search_args = (
                    f'hybrid: {{ query: "{escaped_query}", '
                    f"vector: {vector_literal}, alpha: {request.alpha} }}"
                )
            else:  # semantic
                search_args = f"nearVector: {{ vector: {vector_literal} }}"

        gql = f"""
        {{
            Get {{
                {collection_name}(
                    {search_args}
                    tenant: "{tenant_name}"
                    {where_clause}
                    limit: {request.limit}
                ) {{
                    document_id
                    original_filename
                    content
                    chunk_index
                    _additional {{ id score certainty distance }}
                }}
            }}
        }}
        """
        return {"query": gql}

    async def _fallback_search(
        self,
        workspace_id: str,
        request: SearchRequest,
    ) -> list[SearchResult]:
        """Fallback to PostgreSQL full-text search when Weaviate is unavailable."""
        logger.warning("Using PostgreSQL fallback for search", workspace_id=workspace_id)

        async with self.database.session() as session:
            from sqlalchemy import text

            # Simple LIKE search as fallback
            query = text(
                """
                SELECT c.id as chunk_id, c.document_id,
                       d.original_filename as document_name,
                       c.content, 1.0 as score
                FROM document_chunks c
                JOIN processed_documents d ON c.document_id = d.document_id
                WHERE d.workspace_id = :workspace_id
                  AND c.content ILIKE :search_pattern
                ORDER BY c.chunk_index
                LIMIT :limit
            """
            )

            result = await session.execute(
                query,
                {
                    "workspace_id": workspace_id,
                    "search_pattern": f"%{request.query}%",
                    "limit": request.limit,
                },
            )
            rows = result.fetchall()

            return [
                SearchResult(
                    chunk_id=str(row.chunk_id),
                    document_id=str(row.document_id),
                    document_name=row.document_name,
                    content=row.content,
                    score=row.score,
                )
                for row in rows
            ]

    def _format_where(self, filter_dict: dict) -> str:
        """Format a where filter dict as Weaviate GraphQL syntax."""
        # Convert dict to JSON-like string but without quotes on keys
        json_str = json.dumps(filter_dict)
        # Remove quotes from keys (Weaviate GraphQL syntax)
        return re.sub(r'"(\w+)":', r"\1:", json_str)


# Singleton
_search_service: SearchService | None = None


async def get_search_service() -> SearchService:
    """Get the search service instance."""
    global _search_service
    if _search_service is None:
        database = await get_database()
        _search_service = SearchService(database, settings.effective_weaviate_url)
    return _search_service


async def close_search_service() -> None:
    """Close the search service."""
    global _search_service
    if _search_service is not None:
        await _search_service.close()
        _search_service = None
