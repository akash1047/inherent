"""Text extraction activity for converting document content to plain text.

Fetches file content directly from storage (instead of receiving bytes
via gRPC) and writes extracted text to the staging table.

Extraction dispatch (#117)
---------------------------
Which function handles a content type used to be an if/elif chain here,
duplicating the allow-list REST/MCP validation maintained independently in
``inh-public-api-svc``. Dispatch is now driven by the shared
``inh_contracts.FILE_TYPE_REGISTRY`` (the same registry REST/MCP validate
against): ``_resolve_extractor`` looks up the registry entry for a content
type and then the function wired for it in ``EXTRACTORS`` below. Two
failure modes are explicit and tested (see ``test_temporal_activities.py::
TestFileTypeRegistryDispatch``), never a silent lossy decode:

- No registry entry for the content type at all -> the document fails with
  a message naming the type and the supported set.
- A registry entry exists but its ``extractor`` key has no function in
  ``EXTRACTORS`` -- a wiring bug (a sibling format issue added a
  ``FileTypeSpec`` without its extractor) -- fails with a message that says
  so, instead of a bare ``KeyError`` crashing the Temporal worker.
"""

import io
from collections.abc import Callable

import charset_normalizer
import structlog
from inh_contracts.file_types import all_mime_types, get_spec_for_mime
from temporalio import activity

from src.temporal.lineage import track_event
from src.temporal.models import ExtractTextInput, ExtractTextOutput

logger = structlog.get_logger(__name__)


@activity.defn
async def extract_text(input: ExtractTextInput) -> ExtractTextOutput:
    """Extract text from document content based on content type.

    Which formats are supported, and which function handles each, is defined
    once in ``inh_contracts.FILE_TYPE_REGISTRY`` (#117) -- see the module
    docstring above and ``docs/reference/file-types.md`` for the current
    list, rather than duplicated here where it would drift.

    The activity fetches file content from storage itself (avoiding the
    4MB gRPC limit) and writes extracted text to the staging table.

    Args:
        input: Contains storage refs, content type, filename, and workflow_run_id

    Returns:
        ExtractTextOutput with text_length (text itself is in staging)
    """
    async with track_event(
        workflow_run_id=input.workflow_run_id,
        document_id=input.document_id or "",
        workspace_id=input.workspace_id,
        event_type="text_extracted",
    ):
        return await _extract_text_inner(input)


async def _extract_text_inner(input: ExtractTextInput) -> ExtractTextOutput:
    """Inner implementation for text extraction (wrapped by lineage tracking)."""
    from src.temporal.shared_services import get_staging_service, get_storage_service

    # Fetch file content from storage
    storage_service = get_storage_service()

    if input.storage_backend == "local":
        content = storage_service.read_file(
            path=input.storage_path,
            backend="local",
            bucket=input.storage_bucket,
        )
    elif input.storage_backend == "gcs":
        content = storage_service.read_file(
            path=input.storage_path,
            backend="gcs",
            bucket=input.storage_bucket,
        )
    elif input.storage_backend == "s3":
        content = storage_service.read_file(
            path=input.storage_path,
            backend="s3",
            bucket=input.storage_bucket,
        )
    elif input.storage_backend == "azure":
        if input.storage_url:
            content = storage_service.read_file_from_url(input.storage_url)
        else:
            raise RuntimeError(f"Storage backend '{input.storage_backend}' requires storage_url")
    else:
        raise RuntimeError(f"Unknown storage backend: {input.storage_backend}")

    if content is None:
        raise RuntimeError("Failed to fetch document content from storage")

    content_type = input.content_type.lower()
    filename = input.original_filename.lower()

    logger.info(
        "Extracting text",
        content_type=content_type,
        filename=filename,
        content_size=len(content),
    )

    # Dispatch via the shared FILE_TYPE_REGISTRY (#117) -- see the module
    # docstring. `_resolve_extractor` raises a specific, actionable
    # RuntimeError for either "no registry entry" or "registry entry with no
    # wired extractor"; there is deliberately no catch-all decode-as-text
    # fallback anymore -- an unrecognized type must fail the document, never
    # silently produce garbled chunks.
    extractor = _resolve_extractor(content_type)
    text = extractor(content, input.original_filename)

    # Run data quality checks on extracted text
    from src.services.quality import DataQualityService

    quality = DataQualityService()
    quality_results = quality.check_extracted_text(text, input.original_filename)
    quality.log_results(quality_results, document_id="extract:" + input.workflow_run_id)
    if quality.has_critical_failure(quality_results):
        raise RuntimeError(
            f"Text quality check failed for {input.original_filename}: empty extraction"
        )

    # Strip NUL (0x00) bytes before staging (issue #84). Postgres text/varchar
    # columns cannot store the NUL byte at all -- the driver raises before the
    # query reaches the server -- so an unsanitized value fails the staging
    # write permanently. Some documents (e.g. PDFs pypdf decodes imperfectly)
    # produce embedded NUL bytes. We strip *after* the quality check so its
    # `no_binary_content` diagnostic still sees the raw signal, and before the
    # empty-text guard so a text made up entirely of NUL bytes is caught below.
    if "\x00" in text:
        null_count = text.count("\x00")
        text = text.replace("\x00", "")
        logger.warning(
            "Stripped NUL bytes from extracted text before staging",
            filename=input.original_filename,
            null_bytes_removed=null_count,
        )

    if not text.strip():
        raise RuntimeError(
            f"Text extraction produced empty result for {filename} "
            f"(content_type={content_type}, size={len(content)} bytes)"
        )

    logger.info(
        "Text extracted successfully",
        content_type=content_type,
        text_length=len(text),
    )

    # Write extracted text to staging
    staging = get_staging_service()
    staging.write_text(input.workflow_run_id, text)

    return ExtractTextOutput(text_length=len(text))


def _decode_text(content: bytes) -> str:
    """Decode raw bytes to text without ever silently dropping bytes (#117).

    1. Try strict UTF-8 first: the overwhelming common case for uploaded
       text/markdown/csv/html content, and the only decoding that's provably
       correct when it succeeds -- it also handles content with embedded NUL
       bytes exactly right (needed for the #84 NUL-stripping step above),
       where encoding-detection heuristics on short/ambiguous input can
       misfire (see ``test_temporal_activities.py::TestDecodeText``).
    2. If the bytes are NOT valid UTF-8, use charset-normalizer to detect the
       actual encoding (Windows-1252, UTF-16, ...) and decode with it. This
       replaces the previous ``content.decode("utf-8", errors="ignore")``,
       which silently DELETED every byte that wasn't valid UTF-8 -- data loss
       with no signal, not even a log line.
    3. If detection can't confidently identify an encoding either, fall back
       to UTF-8 with replacement characters (a visible mojibake marker)
       rather than silently vanishing the byte.
    """
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        pass

    best = charset_normalizer.from_bytes(content).best()
    if best is not None:
        return str(best)
    return content.decode("utf-8", errors="replace")


def _extract_json_text(content: bytes) -> str:
    """Parse JSON and pretty-print it as extractable text.

    ``json.loads`` accepts bytes directly (auto-detecting UTF-8/16/32 via any
    BOM present, per the JSON spec), so this needs no separate decode step.
    """
    import json

    data = json.loads(content)
    return json.dumps(data, indent=2)


# Extraction dispatch table (#117): one entry per FileTypeSpec.extractor key
# in inh_contracts.FILE_TYPE_REGISTRY. Adding a sibling format (#118 XLSX,
# #119 PPTX, ...) means adding ONE FileTypeSpec entry (services/inh-contracts)
# and ONE function + entry here -- `test_every_registry_extractor_key_is_wired`
# fails CI if the two ever disagree. Every extractor has the uniform
# ``(content: bytes, filename: str) -> str`` signature `_resolve_extractor`
# dispatches through, even where a given extractor ignores `filename` --
# lambdas adapt the helpers below that predate this table and only take
# `content`, so their own signatures/tests (and imports elsewhere) stay
# untouched. Lambdas also defer name lookup to call time, so this table can
# sit above the helper functions it references without a definition-order
# NameError at import.
EXTRACTORS: dict[str, Callable[[bytes, str], str]] = {
    "text_passthrough": lambda content, filename: _decode_text(content),
    "json_pretty": lambda content, filename: _extract_json_text(content),
    "html": lambda content, filename: _extract_html_text(content),
    "pdf": lambda content, filename: _extract_pdf_text(content),
    "docx": lambda content, filename: _extract_docx_text(content),
    "image_ocr": lambda content, filename: _extract_image_text(content, filename),
}


def _resolve_extractor(content_type: str) -> Callable[[bytes, str], str]:
    """Resolve the extractor function for `content_type`, or fail loudly.

    Two distinct, explicit failure modes (both raise RuntimeError so
    Temporal retries/fails the activity -- never a silent lossy decode):

    1. No FILE_TYPE_REGISTRY entry for this content type at all -- an
       unsupported or unrecognized upload reaching extraction.
    2. A registry entry exists but its ``extractor`` key has no function
       wired into EXTRACTORS -- a wiring bug (a sibling format issue added a
       FileTypeSpec without its extractor), not a bad upload, but it must
       still fail the document with an actionable message instead of a bare
       KeyError crashing the Temporal worker.
    """
    spec = get_spec_for_mime(content_type)
    if spec is None:
        raise RuntimeError(
            f"No extractor registered for content type '{content_type}'. "
            f"Supported types: {', '.join(all_mime_types())}"
        )

    extractor = EXTRACTORS.get(spec.extractor)
    if extractor is None:
        raise RuntimeError(
            f"Registry entry '{spec.key}' ({content_type}) names extractor "
            f"'{spec.extractor}', which has no function wired in EXTRACTORS. "
            f"This is a wiring bug: add EXTRACTORS['{spec.extractor}'] in "
            f"src/temporal/activities/extract.py."
        )
    return extractor


def _extract_pdf_text(content: bytes) -> str:
    """Extract text from PDF content.

    Raises on failure so Temporal retries the activity instead of
    silently producing an empty document.
    """
    try:
        import pypdf
    except ImportError:
        try:
            import PyPDF2 as pypdf  # type: ignore[no-redef]  # noqa: N813
        except ImportError:
            raise RuntimeError("PDF extraction libraries not available (pypdf or PyPDF2)")

    reader = pypdf.PdfReader(io.BytesIO(content))
    text_parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return "\n\n".join(text_parts)


def _extract_docx_text(content: bytes) -> str:
    """Extract text from DOCX content.

    Raises on failure so Temporal retries the activity.
    """
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx not available for DOCX extraction")

    doc = Document(io.BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def _extract_image_text(content: bytes, original_filename: str) -> str:
    """Extract text from a PNG image via Tesseract OCR with graceful fallback.

    OCR is an optional capability (requires the ``ocr`` extra plus the
    ``tesseract`` system binary). When OCR is unavailable -- the libraries
    are not installed, the tesseract binary is missing, or the image simply
    contains no readable text -- this returns a minimal placeholder instead
    of raising. The placeholder keeps the document flowing through the
    pipeline (0 useful chunks, but not a hard failure) so a missing OCR
    install never crashes ingestion.

    Args:
        content: Raw PNG bytes.
        original_filename: Original filename, used in the fallback placeholder.

    Returns:
        OCR-extracted text, or a placeholder string when OCR yields nothing
        or is unavailable.
    """
    placeholder = f"[image: {original_filename}, no text extracted]"

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning(
            "OCR libraries not available (install the 'ocr' extra: pytesseract, pillow); "
            "returning placeholder for image",
            filename=original_filename,
        )
        return placeholder

    try:
        image = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError:
        logger.warning(
            "Tesseract binary not found; install the 'tesseract-ocr' system package. "
            "Returning placeholder for image",
            filename=original_filename,
        )
        return placeholder
    except Exception as e:
        logger.warning(
            "OCR failed for image; returning placeholder",
            filename=original_filename,
            error=str(e),
        )
        return placeholder

    if not text.strip():
        logger.warning(
            "OCR produced no text for image; returning placeholder",
            filename=original_filename,
        )
        return placeholder

    return text


def _extract_html_text(content: bytes) -> str:
    """Extract text from HTML content.

    Falls back to a raw text decode if BeautifulSoup is not available (bs4 is
    a core, non-optional dependency of this service, so this branch is
    defense-in-depth rather than an expected runtime path). Uses
    `_decode_text` (#117) rather than `errors="ignore"` so even this fallback
    never silently drops bytes.
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(content, "html.parser")
        for element in soup(["script", "style"]):
            element.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        logger.warning("beautifulsoup4 not available, falling back to raw decode")
        return _decode_text(content)
