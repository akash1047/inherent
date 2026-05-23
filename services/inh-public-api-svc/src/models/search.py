"""Search-related models."""

from typing import Literal

from pydantic import BaseModel, Field


class ContextChunk(BaseModel):
    """A neighbouring chunk supplied as context for a search result."""

    chunk_id: str
    chunk_index: int
    content: str
    token_count: int = 0


class SearchRequest(BaseModel):
    """Request model for semantic search."""

    query: str = Field(..., min_length=1, max_length=1000, description="Search query")
    limit: int = Field(default=10, ge=1, le=100, description="Maximum results to return")
    min_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum similarity score")
    document_ids: list[str] | None = Field(
        default=None, description="Filter to specific document IDs"
    )

    # Context window (PM-S019)
    include_context: bool = Field(
        default=False,
        description="If true, each result includes surrounding chunks in context_before/after",
    )
    context_window: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Number of chunks before AND after each match (ignored when include_context=false)",
    )

    # Search mode (PM-S018)
    search_mode: Literal["semantic", "hybrid", "keyword"] = Field(
        default="semantic",
        description="Retrieval strategy: semantic (nearText), hybrid (BM25+vector), or keyword (BM25)",
    )
    alpha: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Hybrid fusion weight (1.0=vector-heavy, 0.0=keyword-heavy); ignored unless search_mode=hybrid",
    )


class SearchResult(BaseModel):
    """A single search result."""

    chunk_id: str
    document_id: str
    document_name: str
    content: str
    score: float
    metadata: dict | None = None
    context_before: list[ContextChunk] | None = None
    context_after: list[ContextChunk] | None = None


class SearchResponse(BaseModel):
    """Response model for search endpoint."""

    results: list[SearchResult]
    query: str
    total_results: int
    processing_time_ms: float
    search_mode: Literal["semantic", "hybrid", "keyword"]
    total_tokens: int = 0
