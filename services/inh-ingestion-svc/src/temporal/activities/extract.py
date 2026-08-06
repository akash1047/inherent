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

import datetime
import io
from collections.abc import Callable

import charset_normalizer
import structlog
from inh_contracts.file_types import all_mime_types, get_spec_for_mime
from temporalio import activity
from temporalio.exceptions import ApplicationError

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
    "xlsx": lambda content, filename: _extract_xlsx_text(content),
    "pptx": lambda content, filename: _extract_pptx_text(content),
    "image_ocr": lambda content, filename: _extract_image_text(content, filename),
}


def _resolve_extractor(content_type: str) -> Callable[[bytes, str], str]:
    """Resolve the extractor function for `content_type`, or fail loudly.

    Two distinct, explicit failure modes -- both DETERMINISTIC (the same
    `content_type` will fail identically on every retry, since neither is a
    transient dependency/network condition), so both raise a non-retryable
    ``ApplicationError`` instead of a bare ``RuntimeError``: Temporal fails
    the activity after the FIRST attempt rather than burning the workflow's
    full retry budget (multiple attempts with backoff) on a bug retrying
    cannot fix (#117 review item 13) -- cheaper and faster to reach the same
    terminal `failed` document status. Contrast with other RuntimeErrors in
    this module (storage read failures, a missing extraction library) that
    genuinely may succeed on retry and deliberately keep the default retry
    policy.

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
        raise ApplicationError(
            f"No extractor registered for content type '{content_type}'. "
            f"Supported types: {', '.join(all_mime_types())}",
            type="UnregisteredContentType",
            non_retryable=True,
        )

    extractor = EXTRACTORS.get(spec.extractor)
    if extractor is None:
        raise ApplicationError(
            f"Registry entry '{spec.key}' ({content_type}) names extractor "
            f"'{spec.extractor}', which has no function wired in EXTRACTORS. "
            f"This is a wiring bug: add EXTRACTORS['{spec.extractor}'] in "
            f"src/temporal/activities/extract.py.",
            type="ExtractorWiringBug",
            non_retryable=True,
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


# Cost guards for XLSX extraction (#118 issue requirement: "cap evaluated
# cells (e.g. 500k) and emitted text length; exceeding -> document `failed`
# with actionable error, never OOM"). Both are checked incrementally WHILE
# reading (not after building the full string) so a pathological workbook
# fails fast instead of allocating gigabytes of Python objects first.
_MAX_XLSX_CELLS = 500_000
_MAX_XLSX_TEXT_CHARS = 5_000_000

# Mirrors the XLSX guard above for PPTX: a slide-count ceiling generous
# enough that a genuinely large deck (the #119 issue's illustrative "500
# slides" case) still extracts in full, plus a text-length ceiling as a
# second line of defense against any single pathological slide (e.g. one
# with an enormous table) blowing up memory even under the slide cap.
_MAX_PPTX_SLIDES = 5_000
_MAX_PPTX_TEXT_CHARS = 5_000_000


def _format_xlsx_cell(value: object) -> str:
    """Render one cell's value deterministically (#118 acceptance criterion:
    "Numbers and dates render deterministically; formula cells render
    computed values").

    ``openpyxl`` (opened with ``data_only=True``, see `_extract_xlsx_text`)
    already resolves formula cells to their last-computed value before this
    function ever sees them, so there is no formula-vs-literal branch here --
    every value arriving is already the value to render. `datetime`/`date`
    get an explicit ISO-8601 rendering (stable across locale/platform, unlike
    ``str()`` on a `datetime`, which is locale-INDEPENDENT for
    ``datetime`` too, but explicit is clearer than relying on that
    implementation detail holding forever); every other type (str, int,
    float, bool) is already deterministic under plain `str()`.
    """
    if value is None:
        return ""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def _extract_xlsx_text(content: bytes) -> str:
    """Extract text from XLSX content with row-aware, sheet-boundary
    serialization (#118).

    Per sheet, emits ``## Sheet: <name>`` then one pipe-delimited line per
    non-empty row, cells in column order -- so an agent reading the
    flattened text can still tell which value sat in which column (row-aware
    serialization) and which sheet a row came from (sheet boundaries), the
    two properties #118 requires for the output to be useful to an AI-agent
    reader rather than an undifferentiated wall of cell values.

    ``data_only=True`` reads each formula cell's last-COMPUTED value (the
    cached result Excel/LibreOffice stores when it saves the file) rather
    than the formula source text -- exactly the "computed values only, no
    formula source" contract in the #118 issue. ``read_only=True`` streams
    rows instead of loading the whole workbook into memory, which is also
    what makes the incremental cell-count cap below actually protective
    instead of cosmetic (the OOM the cap prevents would otherwise already
    have happened by the time a non-read-only load finished).

    Raises:
        RuntimeError: openpyxl can't open `content` at all (corrupt/
            truncated zip, password-protected/OLE2 file, a legitimately
            different binary format sharing the OOXML zip signature -- see
            inh_contracts.file_types's docx entry comment), the evaluated-
            cell cap is exceeded, or the emitted text exceeds the character
            cap. Every one of these is a clear, actionable message -- never
            a bare zipfile/openpyxl exception surfacing to the caller, and
            never a silent partial result.
    """
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl not available for XLSX extraction")

    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:
        # Covers corrupt/truncated zips (zipfile.BadZipFile), password-
        # protected files (OLE2/CFBF container -- not a zip at all), and any
        # other "openpyxl couldn't make sense of this" failure -- one clear
        # message instead of a library-specific exception type leaking out.
        raise RuntimeError(f"Failed to open XLSX workbook: {e}") from e

    sheet_parts: list[str] = []
    total_cells = 0
    try:
        for sheet in workbook.worksheets:
            sheet_lines = [f"## Sheet: {sheet.title}"]
            for row in sheet.iter_rows(values_only=True):
                total_cells += len(row)
                if total_cells > _MAX_XLSX_CELLS:
                    raise RuntimeError(
                        f"XLSX exceeds the {_MAX_XLSX_CELLS}-cell evaluated-cell "
                        f"cap (hit while reading sheet '{sheet.title}'). Split "
                        f"the workbook into smaller files and re-upload."
                    )
                # Skip fully blank rows (read-only mode yields a None-filled
                # row for a blank row, and for every row spanned by a merged
                # cell past its top-left anchor) -- an all-None row carries
                # no information worth a pipe-delimited line of empty cells.
                if all(cell is None for cell in row):
                    continue
                sheet_lines.append(" | ".join(_format_xlsx_cell(cell) for cell in row))
            sheet_parts.append("\n".join(sheet_lines))
    finally:
        # read_only workbooks hold an open zip/file handle until closed --
        # always release it, success or failure.
        workbook.close()

    text = "\n\n".join(sheet_parts)
    if len(text) > _MAX_XLSX_TEXT_CHARS:
        raise RuntimeError(
            f"XLSX extracted text exceeds the {_MAX_XLSX_TEXT_CHARS}-character "
            f"cost guard. Split the workbook into smaller files and re-upload."
        )
    return text


def _pptx_slide_title(slide: object) -> str | None:
    """Best-effort slide title, or None if this slide has no title
    placeholder (a valid, common case -- e.g. a section-divider or
    image-only slide)."""
    shapes = getattr(slide, "shapes", None)
    title_shape = getattr(shapes, "title", None) if shapes is not None else None
    if title_shape is None:
        return None
    text = (title_shape.text or "").strip()
    return text or None


def _pptx_slide_notes(slide: object) -> str | None:
    """Speaker notes text for `slide`, or None if it has no notes slide, or
    the notes slide has no non-whitespace text."""
    if not slide.has_notes_slide:
        return None
    notes_text = (slide.notes_slide.notes_text_frame.text or "").strip()
    return notes_text or None


def _extract_pptx_text(content: bytes) -> str:
    """Extract text from PPTX content with slide-boundary sections (#119).

    Per slide, emits ``## Slide <n>: <title>`` (or ``## Slide <n>`` when the
    slide has no title placeholder), then every text-frame shape's text in
    shape order (reading order as authored), then any table shape's rows
    pipe-delimited (same row-aware convention as XLSX, #118), then speaker
    notes under a ``Notes:`` line -- so a query matching only speaker-notes
    text still lands in the same chunk as its slide's visible content once
    #129's chunker splits on these section boundaries. Embedded images are
    deliberately excluded in v1 (#119: "no OCR to manage costs" -- consistent
    with PNG's OCR being an explicit opt-in optional extra elsewhere in this
    module, not a default-on cost for every upload).

    Raises:
        RuntimeError: python-pptx can't open `content` at all (corrupt/
            truncated zip, password-protected/OLE2 file, a different binary
            format sharing the OOXML zip signature), the slide-count cost
            guard is exceeded, or the emitted text exceeds the character
            cap. Same "clear, actionable, never silent" contract as XLSX
            above.
    """
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("python-pptx not available for PPTX extraction")

    try:
        presentation = Presentation(io.BytesIO(content))
    except Exception as e:
        # Covers corrupt/truncated zips, password-protected (OLE2/CFBF)
        # files, and any other "python-pptx couldn't open this" failure.
        raise RuntimeError(f"Failed to open PPTX presentation: {e}") from e

    slide_parts: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        if index > _MAX_PPTX_SLIDES:
            raise RuntimeError(
                f"PPTX exceeds the {_MAX_PPTX_SLIDES}-slide cap. Split the "
                f"deck into smaller files and re-upload."
            )

        title = _pptx_slide_title(slide)
        heading = f"## Slide {index}: {title}" if title else f"## Slide {index}"
        slide_lines = [heading]

        for shape in slide.shapes:
            if shape.has_text_frame:
                # Title text is already in the heading above -- skip it here
                # so it isn't duplicated in the body.
                if shape == slide.shapes.title:
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    paragraph_text = "".join(run.text for run in paragraph.runs)
                    if paragraph_text.strip():
                        slide_lines.append(paragraph_text)
            elif shape.has_table:
                for row in shape.table.rows:
                    slide_lines.append(" | ".join(cell.text for cell in row.cells))

        notes = _pptx_slide_notes(slide)
        if notes:
            slide_lines.append("Notes:")
            slide_lines.append(notes)

        slide_parts.append("\n".join(slide_lines))

    text = "\n\n".join(slide_parts)
    if len(text) > _MAX_PPTX_TEXT_CHARS:
        raise RuntimeError(
            f"PPTX extracted text exceeds the {_MAX_PPTX_TEXT_CHARS}-character "
            f"cost guard. Split the deck into smaller files and re-upload."
        )
    return text


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
