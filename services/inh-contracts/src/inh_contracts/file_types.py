"""File-type support registry -- the single contract for validation, sniffing,
extraction dispatch, and docs (#117).

Problem this replaces
----------------------
Before this module, "what file types does Inherent accept" was answered
independently in five places that had to be edited in lockstep, with nothing
enforcing agreement between them:

- ``services/inh-public-api-svc/src/config/constants.py`` -- ``ALLOWED_MIME_TYPES``
- ``services/inh-public-api-svc/src/mcp_server/server.py`` -- ``SUPPORTED_TEXT_MIME_TYPES``,
  derived from ``ALLOWED_MIME_TYPES`` by a ``.startswith("text/")`` string guess
- ``services/inh-ingestion-svc/src/temporal/activities/extract.py`` -- the
  ``_extract_text_inner`` content-type if/elif dispatch
- ``docs/index.md``, ``docs/reference/mcp-tools.md``,
  ``docs/reference/configuration.md``, ``docs/examples/README.md``
- ``tests/test_extraction_by_type.py``, ``tests/unit/test_upload_document.py``

Same drift class as #9 (README/validation/extraction disagreement) and the
same registry lesson as #100 (the MCP ``_TOOLS`` registry).

Both services now import ``FILE_TYPE_REGISTRY`` (or the derived helpers
below) instead of hardcoding their own list. Docs are generated from /
verified against it (``scripts/generate_supported_formats.py`` +
``services/inh-public-api-svc/tests/unit/test_docs_sync.py``). A content
type reaching ingestion with no matching entry hard-fails the document
instead of silently ``decode(errors="ignore")``-ing it.

Two contract holes this closes (see the #117 issue body):

1. MIME type is entirely client-supplied and was never checked against the
   actual bytes -- a mislabeled binary (PNG uploaded as ``text/plain``)
   passed validation and was garbled downstream. See ``sniff_content_type``.
2. A type accepted at upload but missing from the extraction dispatch fell
   through to a lossy default decode instead of a hard failure. There is no
   default branch anymore: a content type with no registry entry (or a
   registry entry with no wired extractor) is itself the signal to fail the
   document with an actionable ``error_message``.

This module is intentionally dependency-light (stdlib only): both services
depend on it, and it must never force either one to install extraction
libraries (pypdf, python-docx, pytesseract, ...) it doesn't otherwise need.
The ``extractor`` field is therefore a string dispatch KEY, not an import --
the actual function lives in ``inh-ingestion-svc``'s extraction module and is
looked up by that key (see ``EXTRACTORS`` there, and
``test_file_types_contract.py`` which pins that every key here is wired).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

# Strategy family #129's format-aware chunker will branch on. A closed Literal
# (not a free string) so a typo can't silently mint a new, unhandled hint --
# it fails at the FileTypeSpec call site instead of at chunk time.
ChunkingHint = Literal["prose", "tabular", "structured", "media"]

# Which upload surface(s) accept a type. "mcp" additionally exposes it through
# the MCP `upload_document` tool, which only transports inline UTF-8 TEXT (#87
# Task 3 -- MCP tool arguments are JSON strings, so binary bytes cannot cross
# that boundary at all). Binary formats are REST-only by construction, not by
# policy choice.
Surface = Literal["rest", "mcp"]

# What happens when `optional_extra` is required but not installed.
# - "hard_fail": extraction raises; the document is marked failed.
# - "placeholder": extraction returns a placeholder string so the document
#   still flows through the pipeline (0 useful chunks, but not a hard
#   failure) -- mirrors image/png's existing OCR-unavailable fallback.
# Only meaningful when `optional_extra` is set: with no optional dependency,
# a missing REQUIRED library is always a hard failure regardless of this
# field's value.
Degradation = Literal["hard_fail", "placeholder"]


@dataclass(frozen=True)
class FileTypeSpec:
    """Everything one file type needs to fully describe itself (#117).

    Every field answers a question some now-deleted piece of scattered code
    used to answer independently:

    ============================ ===========================================
    Field                        Replaces
    ============================ ===========================================
    ``mime_types``                ``ALLOWED_MIME_TYPES`` membership check
    ``surfaces``                  ``SUPPORTED_TEXT_MIME_TYPES`` string guess
    ``extractor``                 the ``extract.py`` if/elif dispatch
    ``magic``                     nothing -- the verification hole #117 closes
    ``chunking_hint``              input to #129's format-aware chunker
    ``optional_extra``/``degradation``  the ad hoc OCR-availability try/except
    ``max_size_bytes``            per-format override of the global cap
    ============================ ===========================================
    """

    # Short, stable identifier. Used as the extraction dispatch key and in
    # error messages/logs -- an internal name, never shown as the "type" to
    # an end user (that's `mime_types[0]`).
    key: str

    # Canonical MIME type first, any accepted aliases after. All are valid
    # values for the upload's declared Content-Type.
    mime_types: tuple[str, ...]

    # Filename extensions (with leading dot), e.g. (".md", ".markdown").
    # Reserved as a fallback classifier for a generic/absent content-type
    # (e.g. "application/octet-stream") -- not yet consulted by the current
    # REST/MCP upload paths, which trust the declared MIME type outright, but
    # part of the contract so a future extension-based consumer (e.g. #130's
    # ZIP member classification) has exactly one place to look instead of
    # re-deriving its own extension list.
    extensions: tuple[str, ...]

    # Magic-byte signature checked at intake (see `sniff_content_type`).
    # None for every current text format -- there is no binary signature to
    # check for free-form text, so the sniff for those relies entirely on the
    # cross-check against OTHER specs' signatures (a text/plain upload whose
    # bytes match a known binary signature is still caught).
    magic: bytes | None

    # Which upload surface(s) accept this type.
    surfaces: frozenset[Surface]

    # Dispatch key into inh-ingestion-svc's EXTRACTORS map
    # (src/temporal/activities/extract.py). A string, not a callable/import,
    # so this package stays free of extraction-library dependencies.
    extractor: str

    # Strategy family #129's format-aware chunker will branch on.
    chunking_hint: ChunkingHint

    # pyproject optional-dependency group gating a heavy/optional extractor
    # library (existing pattern: "ocr" for pytesseract+pillow). None means
    # the extractor's dependencies are part of the service's core install.
    optional_extra: str | None = None

    # Behavior when `optional_extra` is required but missing. See the
    # `Degradation` docstring above.
    degradation: Degradation = "hard_fail"

    # Per-format upload size cap override, in bytes. None means "use the
    # service's global MAX_UPLOAD_SIZE_BYTES default".
    max_size_bytes: int | None = None


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
# One entry per currently-supported format. Order here is the order rendered
# in error messages and generated docs -- matches the historical
# ALLOWED_MIME_TYPES / docs/index.md ordering (plain text, Markdown, CSV,
# HTML, JSON, PDF, DOCX, PNG) so this migration changes no user-visible
# ordering.
#
# Adding a NEW format (the whole point of #117) is:
#   1. One FileTypeSpec entry below.
#   2. One function + EXTRACTORS[key] entry in inh-ingestion-svc's extract.py.
#   3. `uv run python scripts/generate_supported_formats.py` to refresh docs.
# REST validation, MCP exposure (if `surfaces` includes "mcp"), extraction
# dispatch, and the docs table all pick it up with no other edits.
FILE_TYPE_REGISTRY: tuple[FileTypeSpec, ...] = (
    FileTypeSpec(
        key="txt",
        mime_types=("text/plain",),
        extensions=(".txt",),
        magic=None,
        surfaces=frozenset({"rest", "mcp"}),
        extractor="text_passthrough",
        chunking_hint="prose",
    ),
    FileTypeSpec(
        key="markdown",
        mime_types=("text/markdown",),
        extensions=(".md", ".markdown"),
        magic=None,
        surfaces=frozenset({"rest", "mcp"}),
        extractor="text_passthrough",
        chunking_hint="prose",
    ),
    FileTypeSpec(
        key="csv",
        mime_types=("text/csv",),
        extensions=(".csv",),
        magic=None,
        surfaces=frozenset({"rest", "mcp"}),
        extractor="text_passthrough",
        chunking_hint="tabular",
    ),
    FileTypeSpec(
        key="html",
        mime_types=("text/html",),
        extensions=(".html", ".htm"),
        magic=None,
        surfaces=frozenset({"rest", "mcp"}),
        extractor="html",
        chunking_hint="prose",
    ),
    FileTypeSpec(
        key="json",
        mime_types=("application/json",),
        extensions=(".json",),
        magic=None,
        # REST-only: MCP upload_document is text/*-only by design (#87 Task
        # 3), and JSON is a distinct content family even though it's
        # transported as text.
        surfaces=frozenset({"rest"}),
        extractor="json_pretty",
        chunking_hint="structured",
    ),
    FileTypeSpec(
        key="pdf",
        mime_types=("application/pdf",),
        extensions=(".pdf",),
        magic=b"%PDF-",
        surfaces=frozenset({"rest"}),
        extractor="pdf",
        chunking_hint="prose",
    ),
    FileTypeSpec(
        key="docx",
        mime_types=("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        extensions=(".docx",),
        # DOCX is a ZIP container (OOXML); PK\x03\x04 is the local-file-header
        # signature every ZIP starts with. NOTE: this signature is shared by
        # every OOXML sibling format (#118 XLSX, #119 PPTX) and by ZIP itself
        # (#130) -- a 4-byte prefix cannot distinguish "this zip is a .docx"
        # from "this zip is a .xlsx". It DOES still catch a non-zip file
        # (text, PNG, ...) mislabeled as docx, which is what #117 requires;
        # disambiguating between OOXML siblings needs inspecting the zip's
        # internal `[Content_Types].xml`, left to whichever of #118/#119 lands
        # second.
        magic=b"PK\x03\x04",
        surfaces=frozenset({"rest"}),
        extractor="docx",
        chunking_hint="prose",
    ),
    FileTypeSpec(
        key="png",
        mime_types=("image/png",),
        extensions=(".png",),
        magic=b"\x89PNG\r\n\x1a\n",
        surfaces=frozenset({"rest"}),
        extractor="image_ocr",
        chunking_hint="media",
        optional_extra="ocr",
        degradation="placeholder",
    ),
)


# ---------------------------------------------------------------------------
# Lookups derived from the registry -- REST, MCP, and extraction all call
# these instead of maintaining their own copy.
# ---------------------------------------------------------------------------


def get_spec_for_mime(mime_type: str) -> FileTypeSpec | None:
    """Look up the registry entry whose ``mime_types`` contains `mime_type`.

    Case-insensitive/whitespace-tolerant since Content-Type headers are
    client-supplied and inconsistently cased in the wild.
    """
    normalized = mime_type.strip().lower()
    for spec in FILE_TYPE_REGISTRY:
        if normalized in spec.mime_types:
            return spec
    return None


def get_spec_for_extension(extension: str) -> FileTypeSpec | None:
    """Look up the registry entry whose ``extensions`` contains `extension`.

    Accepts the extension with or without a leading dot (".md" or "md").
    """
    normalized = extension if extension.startswith(".") else f".{extension}"
    normalized = normalized.strip().lower()
    for spec in FILE_TYPE_REGISTRY:
        if normalized in spec.extensions:
            return spec
    return None


def get_spec_by_key(key: str) -> FileTypeSpec | None:
    """Look up a registry entry by its short `key` (e.g. "pdf")."""
    for spec in FILE_TYPE_REGISTRY:
        if spec.key == key:
            return spec
    return None


def all_mime_types() -> list[str]:
    """Every accepted MIME type across all registered formats.

    Replaces the old hand-maintained ``ALLOWED_MIME_TYPES`` list: REST
    upload validation, the 400 error text, and generated docs all derive
    from this so they cannot disagree about what "supported" means.
    """
    return [mime for spec in FILE_TYPE_REGISTRY for mime in spec.mime_types]


def mcp_mime_types() -> tuple[str, ...]:
    """MIME types the MCP ``upload_document`` tool accepts.

    Replaces the old ``ALLOWED_MIME_TYPES`` ``.startswith("text/")`` guess in
    ``mcp_server/server.py``. That heuristic happened to be correct only
    because every current MCP-eligible type's MIME starts with "text/" --
    the moment a sibling issue adds a text/*-prefixed type that ISN'T
    MCP-safe, or a non-"text/"-prefixed type that IS (e.g. a future
    structured format transported as text), the heuristic silently
    misclassifies it. ``surfaces`` makes the decision an explicit, per-type
    fact in the registry instead of an inferred string property.
    """
    return tuple(
        sorted(
            mime
            for spec in FILE_TYPE_REGISTRY
            if "mcp" in spec.surfaces
            for mime in spec.mime_types
        )
    )


# ---------------------------------------------------------------------------
# Intake-time sniffing -- closes hole #1 from the module docstring
# ---------------------------------------------------------------------------


class UnknownContentTypeError(ValueError):
    """A declared/stored content type has no matching registry entry."""

    def __init__(self, declared_mime: str):
        self.declared_mime = declared_mime
        super().__init__(
            f"Unsupported content type '{declared_mime}'. "
            f"Supported types: {', '.join(all_mime_types())}"
        )


class ContentTypeMismatchError(ValueError):
    """A file's magic bytes contradict its declared content type."""

    def __init__(self, declared_mime: str, reason: str):
        self.declared_mime = declared_mime
        self.reason = reason
        super().__init__(
            f"File content does not match the declared content type "
            f"'{declared_mime}': {reason}."
        )


def sniff_content_type(content: bytes, declared_mime: str) -> FileTypeSpec:
    """Validate that `content`'s magic bytes agree with `declared_mime` (#117).

    MIME type is entirely client-supplied and, before this function existed,
    was never checked against the actual bytes -- a mislabeled binary (e.g.
    PNG bytes declared as ``text/plain``) passed validation and was garbled
    downstream instead of rejected. Two checks, run in both directions so
    either a wrong "this IS a real binary format" claim or a wrong "this is
    just text" claim gets caught:

    1. `declared_mime` maps to a spec with a known signature -> `content`
       MUST start with it (catches "declared PDF, isn't actually PDF").
    2. `content`'s bytes match a DIFFERENT spec's signature than the
       declared one -> still a mismatch (catches "PNG bytes declared as
       text/plain", where text/plain has no signature of its own for
       check 1 to fail on).

    Formats with no magic signature (every current text/* format) skip
    check 1 -- there is nothing to compare against -- but remain subject to
    check 2, so a binary file mislabeled as text is still caught.

    Returns the resolved ``FileTypeSpec`` for `declared_mime` on success.

    Raises:
        UnknownContentTypeError: `declared_mime` has no registry entry.
        ContentTypeMismatchError: the bytes contradict `declared_mime`.
    """
    spec = get_spec_for_mime(declared_mime)
    if spec is None:
        raise UnknownContentTypeError(declared_mime)

    if spec.magic is not None and not content.startswith(spec.magic):
        raise ContentTypeMismatchError(
            declared_mime,
            f"expected the '{spec.key}' file signature but the bytes did not match it",
        )

    for other in FILE_TYPE_REGISTRY:
        if other.magic is None or other.key == spec.key:
            continue
        if content.startswith(other.magic):
            raise ContentTypeMismatchError(
                declared_mime,
                f"the bytes match the '{other.key}' file signature instead",
            )

    return spec


class ExtensionMismatchError(ValueError):
    """A filename's extension belongs to a DIFFERENT registered type than
    the one resolved from the declared content type."""

    def __init__(self, filename: str, declared_key: str, extension_key: str):
        self.filename = filename
        self.declared_key = declared_key
        self.extension_key = extension_key
        super().__init__(
            f"Filename '{filename}' has an extension registered to type "
            f"'{extension_key}', which does not match the declared content "
            f"type (resolved to '{declared_key}')."
        )


def check_extension_consistency(filename: str, declared_spec: FileTypeSpec) -> None:
    """Cross-check a filename's extension against the DECLARED type (#117).

    Three independent signals describe an upload: the declared content type,
    the filename's extension, and the actual bytes. `sniff_content_type`
    checks bytes against the declared type; this checks the filename against
    the declared type. Between the two, any pairwise disagreement among the
    three signals is caught by at least one of them -- e.g. a file named
    ``report.pdf`` whose bytes are actually a PNG is caught here if it's
    declared ``image/png`` (extension says pdf, declared says png) or by
    `sniff_content_type` if it's declared ``application/pdf`` (declared says
    pdf, bytes say png).

    Deliberately permissive when the extension is NOT one this registry
    recognizes (e.g. ``.log``, ``.yaml`` -- formats #117 doesn't cover yet,
    or no extension at all, e.g. the REST route's ``"unnamed"`` fallback):
    content type remains the authoritative signal, and an unrecognized
    extension is not evidence of anything, so it is silently allowed rather
    than treated as suspicious. Only a KNOWN extension mapping to a
    DIFFERENT spec than `declared_spec` is a real, actionable disagreement.

    Raises:
        ExtensionMismatchError: the filename's extension is registered to a
            different type than `declared_spec`.
    """
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not extension:
        return

    extension_spec = get_spec_for_extension(extension)
    if extension_spec is None or extension_spec.key == declared_spec.key:
        return

    raise ExtensionMismatchError(filename, declared_spec.key, extension_spec.key)


# ---------------------------------------------------------------------------
# Docs generation -- closes the "docs can drift from code" defect (#117)
# ---------------------------------------------------------------------------


def render_markdown_table() -> str:
    """Render the supported-file-types table straight from the registry.

    ``docs/reference/file-types.md`` embeds this exact string between
    generated-content markers. ``scripts/generate_supported_formats.py``
    regenerates it; ``test_docs_sync.py`` (inh-public-api-svc) fails CI the
    moment the checked-in table and this function disagree -- the docs/code
    drift #117 exists to prevent, made unable to happen silently.
    """
    header = (
        "| Type | Extension(s) | MIME type(s) | Surfaces | Chunking hint | Extra required |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
    )
    rows = []
    for spec in FILE_TYPE_REGISTRY:
        exts = ", ".join(f"`{e}`" for e in spec.extensions)
        mimes = ", ".join(f"`{m}`" for m in spec.mime_types)
        # Stable "rest" / "rest + mcp" rendering regardless of frozenset order.
        surfaces = " + ".join(s for s in ("rest", "mcp") if s in spec.surfaces)
        extra = f"`{spec.optional_extra}`" if spec.optional_extra else "—"
        rows.append(
            f"| {spec.key} | {exts} | {mimes} | {surfaces} | {spec.chunking_hint} | {extra} |"
        )
    return header + "\n".join(rows) + "\n"
