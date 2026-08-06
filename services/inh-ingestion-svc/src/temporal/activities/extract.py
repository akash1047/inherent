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

import email
import io
import zipfile
from collections.abc import Callable
from email import policy
from xml.etree import ElementTree as ET

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
    "image_ocr": lambda content, filename: _extract_image_text(content, filename),
    # Long-tail formats (#124/#125/#126).
    "eml": lambda content, filename: _extract_eml_text(content, filename),
    "epub": lambda content, filename: _extract_epub_text(content, filename),
    "rtf": lambda content, filename: _extract_rtf_text(content, filename),
    "odt": lambda content, filename: _extract_odt_text(content, filename),
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


# ---------------------------------------------------------------------------
# #124 -- EML (RFC 822 email)
# ---------------------------------------------------------------------------


def _eml_attachment_label(part: email.message.EmailMessage) -> str:
    """A human-readable label for an EML attachment part, used only to name
    what was elided -- never its content (#124: "silently including their
    filenames as if they were content is not [defensible]" only applies to
    dumping them into the body; a clearly labeled filename listing is fine).
    """
    filename = part.get_filename()
    if filename:
        return filename
    if part.get_content_type() == "message/rfc822":
        # A forwarded/embedded email with no explicit filename -- label it
        # with its own Subject so it's still identifiable. Deliberately does
        # NOT look any deeper than this one header: #124 scopes nested
        # message/rfc822 parts to "first level only", and `iter_attachments`
        # below already only walks the OUTER message's immediate children,
        # so this function never gets asked about a grandchild part.
        try:
            nested = part.get_payload(0)
            # get_payload(0) is typed to possibly return a raw `str` (the
            # non-multipart-message case) as well as a Message -- only a
            # Message has headers to read `.get("Subject")` from.
            subject = nested.get("Subject") if isinstance(nested, email.message.Message) else None
        except (IndexError, AttributeError):
            subject = None
        return f"(embedded message: {subject})" if subject else "(embedded message)"
    return "(unnamed attachment)"


def _extract_eml_text(content: bytes, filename: str) -> str:
    """Extract text from an RFC 822 (.eml) email message (#124).

    An email is a tree, not a document -- three deliberate decisions:

    1. Headers (From/To/Cc/Date/Subject) are what make an email citable and
       searchable for an AI agent reader, so they are ALWAYS emitted first,
       never dropped -- even when there is no body at all.
    2. Body: prefer the text/plain part; fall back to text/html run through
       the EXISTING `_extract_html_text` (no second bespoke HTML parser).
       `email.policy.default`'s `EmailMessage.get_content()` already decodes
       quoted-printable/base64 Content-Transfer-Encoding and any declared
       charset for us -- no manual decode step needed here.
    3. Attachments (v1): NOT extracted. Their filenames (and a count) are
       recorded in a clearly labeled, separate section so an agent knows
       content was elided -- this is explicitly NOT the same as silently
       including filenames as if they were body content. Nested
       message/rfc822 parts are inspected one level only: `iter_attachments`
       walks the OUTER message's immediate children only, so an email
       forwarded as an attachment is listed by name but never recursed into
       for its own body/attachments.

    Raises nothing on its own for a missing body or missing headers -- an
    email with truly no headers, body, or attachments extracts to an empty
    string, and the caller's existing empty-text guard
    (`_extract_text_inner`) is what turns that into the actual document
    failure. This keeps exactly one place responsible for "empty extraction
    is a hard failure" instead of duplicating that check here.
    """
    msg = email.message_from_bytes(content, policy=policy.default)

    header_lines = [
        f"{header}: {value}"
        for header in ("From", "To", "Cc", "Date", "Subject")
        if (value := msg.get(header))
    ]

    body_text = ""
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        raw_body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            # get_content() for text/html already returns a decoded str;
            # re-encode so the bytes-based HTML extractor can strip tags the
            # same way the html/epub/odt paths do.
            body_text = _extract_html_text(raw_body.encode("utf-8"))
        else:
            body_text = raw_body

    attachments = (
        [_eml_attachment_label(part) for part in msg.iter_attachments()]
        if msg.is_multipart()
        else []
    )

    sections = []
    if header_lines:
        sections.append("\n".join(header_lines))
    if body_text.strip():
        sections.append(body_text.strip())
    if attachments:
        sections.append(
            f"[{len(attachments)} attachment(s) not extracted: {', '.join(attachments)}]"
        )

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# #125 -- EPUB (reuses the HTML extraction path)
# ---------------------------------------------------------------------------

# XML namespaces used by the EPUB Open Container Format / Open Packaging
# Format specs -- needed to find the rootfile (container.xml) and to query
# the manifest/spine (content.opf) with ElementTree's namespace-qualified
# `find`/`findall`.
_EPUB_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_EPUB_OPF_NS = {"opf": "http://www.idpf.org/2007/opf"}


def _extract_epub_text(content: bytes, filename: str) -> str:
    """Extract EPUB chapter text in spine (reading) order (#125).

    An EPUB is a ZIP of XHTML documents plus a manifest/spine describing
    their reading order -- this REUSES the existing `_extract_html_text`
    for each chapter rather than writing a second HTML parser, per the
    issue's explicit contract. Spine order (not zip member order) is what
    determines chapter order: `content.opf`'s `<spine>` element is the
    single source of truth for reading sequence, resolved via
    `META-INF/container.xml` -> `content.opf` -> `<manifest>` (id -> href)
    -> `<spine>` (ordered idrefs).

    Failure paths (never a crash, always an actionable RuntimeError):
    - Corrupt zip.
    - Missing/unparseable META-INF/container.xml or content.opf.
    - No spine items at all (nothing to determine chapter order from).
    - DRM/encrypted EPUB, signalled by the standard
      META-INF/encryption.xml manifest -- its mere presence means the
      referenced resources cannot be read as plain XHTML, so this is
      checked and rejected BEFORE attempting to parse any chapter.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise RuntimeError(f"'{filename}' is not a valid EPUB (corrupt zip archive): {e}") from e

    try:
        names = zf.namelist()
    except zipfile.BadZipFile as e:
        raise RuntimeError(
            f"'{filename}' is not a valid EPUB (corrupt zip central directory): {e}"
        ) from e

    if "META-INF/encryption.xml" in names:
        raise RuntimeError(
            f"'{filename}' is a DRM-protected/encrypted EPUB and cannot be extracted."
        )

    try:
        container_xml = zf.read("META-INF/container.xml")
    except KeyError as e:
        raise RuntimeError(
            f"'{filename}' is not a valid EPUB: missing META-INF/container.xml"
        ) from e

    try:
        container_root = ET.fromstring(container_xml)
    except ET.ParseError as e:
        raise RuntimeError(f"'{filename}' has an unparseable META-INF/container.xml: {e}") from e

    rootfile = container_root.find(f".//{{{_EPUB_CONTAINER_NS}}}rootfile")
    if rootfile is None or "full-path" not in rootfile.attrib:
        raise RuntimeError(f"'{filename}' is not a valid EPUB: no rootfile declared")
    opf_path = rootfile.attrib["full-path"]

    try:
        opf_xml = zf.read(opf_path)
    except KeyError as e:
        raise RuntimeError(
            f"'{filename}' is not a valid EPUB: declared content.opf '{opf_path}' is missing"
        ) from e

    try:
        opf_root = ET.fromstring(opf_xml)
    except ET.ParseError as e:
        raise RuntimeError(f"'{filename}' has an unparseable content.opf: {e}") from e

    # Manifest: item id -> its attributes (href, media-type, properties).
    # `properties` carries EPUB3's "nav"/"cover-image" markers used below to
    # skip navigation and cover items.
    manifest = {
        item.attrib["id"]: item.attrib
        for item in opf_root.iterfind(".//opf:manifest/opf:item", _EPUB_OPF_NS)
        if "id" in item.attrib
    }

    spine_items = opf_root.findall(".//opf:spine/opf:itemref", _EPUB_OPF_NS)
    if not spine_items:
        raise RuntimeError(f"'{filename}' has no spine -- cannot determine reading order")

    # Resolve manifest hrefs relative to content.opf's own directory.
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    chapters = []
    for itemref in spine_items:
        item = manifest.get(itemref.attrib.get("idref", ""))
        if item is None:
            continue  # spine references an id the manifest doesn't have -- skip, don't crash
        properties = item.get("properties", "").split()
        if "nav" in properties or "cover-image" in properties:
            continue  # nav/cover items skipped per #125
        if item.get("media-type") not in ("application/xhtml+xml", "text/html"):
            continue  # spine can reference non-markup resources; only chapters are extracted
        try:
            chapter_bytes = zf.read(opf_dir + item["href"])
        except KeyError:
            continue  # manifest references a missing zip member -- skip, don't crash

        chapter_text = _extract_html_text(chapter_bytes).strip()
        if chapter_text:
            chapters.append(chapter_text)

    if not chapters:
        raise RuntimeError(f"'{filename}' has a spine but no chapter produced any extractable text")

    # "## " per spine item (#125 serialization contract): gives #129's
    # future format-aware chunker (`chunking_hint`) explicit chapter
    # boundaries to split on, in true reading order.
    return "\n\n".join(f"## Chapter {i}\n\n{text}" for i, text in enumerate(chapters, start=1))


# ---------------------------------------------------------------------------
# #126 -- RTF and ODT (two distinct formats, two distinct code paths)
# ---------------------------------------------------------------------------


def _extract_rtf_text(content: bytes, filename: str) -> str:
    """Extract text from RTF content via `striprtf` (#126).

    RTF is a control-word format, not XML/ZIP -- kept in its own function
    (not sharing code with `_extract_odt_text` below) so RTF's control-word
    parsing and ODT's zip/XML handling never bleed together.
    `striprtf.rtf_to_text` already handles arbitrarily nested control-word
    groups correctly (that's the whole point of the library), so no bespoke
    nesting logic is needed here.
    """
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError:
        raise RuntimeError("striprtf not available for RTF extraction")

    # RTF is a control-word format where non-ASCII text is escaped inline
    # (\'hh hex escapes, \uNNNN unicode control words) rather than encoded
    # directly in the byte stream. latin-1 is used here purely as a
    # lossless byte<->str round trip (maps all 256 byte values 1:1, so it
    # never raises) -- striprtf resolves the ACTUAL characters from those
    # escapes during parsing, not from this decode step.
    raw_text = content.decode("latin-1")

    try:
        # striprtf ships no type stubs, so its return is untyped `Any` to
        # mypy -- str(...) is a no-op at runtime (rtf_to_text always returns
        # a str) but gives the function's own `-> str` signature a real
        # guarantee instead of just trusting an untyped third party.
        text = str(rtf_to_text(raw_text))
    except Exception as e:
        raise RuntimeError(f"Failed to parse RTF content in '{filename}': {e}") from e

    if not text.strip():
        raise RuntimeError(f"'{filename}' produced no extractable text from RTF content")
    return text


def _extract_odt_text(content: bytes, filename: str) -> str:
    """Extract text from an ODT (OpenDocument Text) `content.xml` (#126).

    ODT is a ZIP container like DOCX/EPUB, but text extraction only needs
    its `content.xml` member -- read via stdlib `zipfile`, then run through
    the SAME BeautifulSoup tag-strip path `_extract_html_text` uses for
    HTML/EPUB, since `content.xml` is just another XML dialect with human
    text inside element bodies (no odfpy dependency needed, per the #126
    contract). Kept in its own function (not sharing code with
    `_extract_rtf_text` above) so ODT's zip/XML handling and RTF's
    control-word parsing never bleed together.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise RuntimeError(f"'{filename}' is not a valid ODT (corrupt zip archive): {e}") from e

    try:
        content_xml = zf.read("content.xml")
    except KeyError as e:
        # Also the exact signal for "extension says .odt but the zip is
        # actually a different OOXML/ZIP payload (e.g. DOCX)": a real ODT
        # always has content.xml at its root; DOCX has word/document.xml
        # instead, so this KeyError is a real, actionable contradiction.
        raise RuntimeError(
            f"'{filename}' is not a valid ODT: no content.xml found in the archive "
            f"(the file may be a different ZIP-based format, e.g. DOCX, saved with "
            f"an .odt extension)"
        ) from e
    except zipfile.BadZipFile as e:
        raise RuntimeError(
            f"'{filename}' is not a valid ODT (corrupt zip central directory): {e}"
        ) from e

    # `_extract_html_text` uses bs4's "html.parser", which is intentionally
    # being pointed at XML here (the #126 contract: "content.xml through the
    # XML tag-strip path" -- no odfpy needed). bs4 warns about that
    # (XMLParsedAsHTMLWarning) even though it's a deliberate, working choice
    # for this generic tag-strip use case, not a mistake -- suppressed here
    # rather than globally so a genuine XML-parser-misuse warning elsewhere
    # in the service is still surfaced.
    import warnings

    from bs4 import XMLParsedAsHTMLWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=XMLParsedAsHTMLWarning)
        text = _extract_html_text(content_xml).strip()

    if not text:
        raise RuntimeError(f"'{filename}' produced no extractable text from content.xml")
    return text
