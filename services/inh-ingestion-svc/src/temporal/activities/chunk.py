"""Text chunking activity for splitting documents into processable chunks.

Reads text from staging (instead of receiving it via gRPC) and writes
chunks back to staging.
"""

import re

import structlog
from temporalio import activity

from src.temporal.lineage import track_event
from src.temporal.models import ChunkData, ChunkTextInput, ChunkTextOutput

logger = structlog.get_logger(__name__)


@activity.defn
async def chunk_text(input: ChunkTextInput) -> ChunkTextOutput:
    """Split text into chunks based on the configured strategy.

    Chunking strategies:
    - sentences: Split by sentence boundaries with configurable overlap
    - paragraphs: Split by double newlines (no overlap)
    - tokens: Fixed-size chunks with overlap

    Reads text from staging and writes chunks back to staging. Only the
    chunk count passes through gRPC.

    Args:
        input: Contains workflow_run_id, document_id, strategy, max_chunk_size, and overlap

    Returns:
        ChunkTextOutput with chunk_count (chunks themselves are in staging)
    """
    async with track_event(
        workflow_run_id=input.workflow_run_id,
        document_id=input.document_id,
        workspace_id=input.workspace_id,
        event_type="text_chunked",
    ):
        return await _chunk_text_inner(input)


async def _chunk_text_inner(input: ChunkTextInput) -> ChunkTextOutput:
    """Inner implementation for text chunking (wrapped by lineage tracking)."""
    from src.temporal.shared_services import get_staging_service

    staging = get_staging_service()

    # Read text from staging
    text = staging.read_text(input.workflow_run_id)

    document_id = input.document_id
    strategy = input.strategy
    max_size = input.max_chunk_size
    overlap = input.chunk_overlap

    logger.info(
        "Chunking text",
        document_id=document_id,
        strategy=strategy,
        text_length=len(text),
        max_chunk_size=max_size,
    )

    if not text:
        return ChunkTextOutput(chunk_count=0)

    chunks: list[ChunkData] = []

    if strategy == "sentences":
        chunks = _chunk_by_sentences(text, document_id, max_size, overlap)
    elif strategy == "paragraphs":
        chunks = _chunk_by_paragraphs(text, document_id, max_size)
    else:  # tokens (default)
        chunks = _chunk_by_size(text, document_id, max_size, overlap)

    logger.info(
        "Text chunked successfully",
        document_id=document_id,
        chunk_count=len(chunks),
    )

    # Run data quality checks on chunks
    from src.services.quality import DataQualityService

    chunks_for_check = [
        {
            "content": c.content,
            "chunk_index": c.chunk_index,
        }
        for c in chunks
    ]
    quality = DataQualityService()
    quality_results = quality.check_chunks(chunks_for_check, filename=document_id)
    quality.log_results(quality_results, document_id=document_id)
    if quality.has_critical_failure(quality_results):
        raise RuntimeError(f"Chunk quality check failed for {document_id}: 0 chunks produced")

    # Write chunks to staging as list of dicts
    chunks_dicts = [
        {
            "document_id": c.document_id,
            "content": c.content,
            "chunk_index": c.chunk_index,
            "start_char": c.start_char,
            "end_char": c.end_char,
        }
        for c in chunks
    ]
    staging.write_chunks(input.workflow_run_id, chunks_dicts)

    return ChunkTextOutput(chunk_count=len(chunks))


def _chunk_by_size(text: str, document_id: str, max_size: int, overlap: int) -> list[ChunkData]:
    """Split text into fixed-size chunks with overlap."""
    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = min(start + max_size, len(text))

        # Try to break at word boundary
        if end < len(text):
            last_space = text.rfind(" ", start, end)
            if last_space > start:
                end = last_space

        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(
                ChunkData(
                    document_id=document_id,
                    content=chunk_text,
                    chunk_index=chunk_index,
                    start_char=start,
                    end_char=end,
                )
            )
            chunk_index += 1

        # Move to next chunk with overlap
        start = end - overlap if end - overlap > start else end

    return chunks


def _chunk_by_sentences(
    text: str, document_id: str, max_size: int, overlap: int
) -> list[ChunkData]:
    """Split text into chunks by sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", text)

    chunks = []
    current_chunk: list[str] = []
    current_size = 0
    chunk_index = 0
    start_char = 0

    for sentence in sentences:
        sentence_len = len(sentence)

        # If adding this sentence exceeds max size, save current chunk
        if current_size + sentence_len > max_size and current_chunk:
            chunk_text = " ".join(current_chunk).strip()
            if chunk_text:
                chunks.append(
                    ChunkData(
                        document_id=document_id,
                        content=chunk_text,
                        chunk_index=chunk_index,
                        start_char=start_char,
                        end_char=start_char + len(chunk_text),
                    )
                )
                chunk_index += 1
                start_char += len(chunk_text) + 1

            # Keep some sentences for overlap
            overlap_sentences: list[str] = []
            overlap_size = 0
            for s in reversed(current_chunk):
                if overlap_size + len(s) <= overlap:
                    overlap_sentences.insert(0, s)
                    overlap_size += len(s)
                else:
                    break

            current_chunk = overlap_sentences
            current_size = overlap_size

        current_chunk.append(sentence)
        current_size += sentence_len

    # Save final chunk
    if current_chunk:
        chunk_text = " ".join(current_chunk).strip()
        if chunk_text:
            chunks.append(
                ChunkData(
                    document_id=document_id,
                    content=chunk_text,
                    chunk_index=chunk_index,
                    start_char=start_char,
                    end_char=start_char + len(chunk_text),
                )
            )

    return chunks


def _chunk_by_paragraphs(text: str, document_id: str, max_size: int) -> list[ChunkData]:
    """Split text into chunks by paragraphs."""
    paragraphs = text.split("\n\n")

    chunks = []
    current_chunk: list[str] = []
    current_size = 0
    chunk_index = 0
    start_char = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_len = len(para)

        # If adding this paragraph exceeds max size, save current chunk
        if current_size + para_len > max_size and current_chunk:
            chunk_text = "\n\n".join(current_chunk).strip()
            if chunk_text:
                chunks.append(
                    ChunkData(
                        document_id=document_id,
                        content=chunk_text,
                        chunk_index=chunk_index,
                        start_char=start_char,
                        end_char=start_char + len(chunk_text),
                    )
                )
                chunk_index += 1
                start_char += len(chunk_text) + 2

            current_chunk = []
            current_size = 0

        current_chunk.append(para)
        current_size += para_len

    # Save final chunk
    if current_chunk:
        chunk_text = "\n\n".join(current_chunk).strip()
        if chunk_text:
            chunks.append(
                ChunkData(
                    document_id=document_id,
                    content=chunk_text,
                    chunk_index=chunk_index,
                    start_char=start_char,
                    end_char=start_char + len(chunk_text),
                )
            )

    return chunks
