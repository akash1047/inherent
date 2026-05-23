"""Input validation and sanitization utilities."""

import re
import unicodedata
from uuid import UUID

from src.config.constants import MAX_SEARCH_QUERY_LENGTH


def sanitize_search_query(query: str) -> str:
    """Sanitize a search query string.

    - Strips leading/trailing whitespace
    - Normalizes unicode to NFC form
    - Removes control characters
    - Truncates to max length
    - Collapses multiple whitespace to single space

    Args:
        query: Raw search query from user.

    Returns:
        Sanitized query string.
    """
    if not query:
        return ""

    # Normalize unicode
    query = unicodedata.normalize("NFC", query)

    # Remove control characters (except newlines/tabs)
    query = "".join(
        char for char in query if not unicodedata.category(char).startswith("C") or char in "\n\t"
    )

    # Strip whitespace
    query = query.strip()

    # Collapse multiple whitespace
    query = re.sub(r"\s+", " ", query)

    # Truncate to max length
    if len(query) > MAX_SEARCH_QUERY_LENGTH:
        query = query[:MAX_SEARCH_QUERY_LENGTH]

    return query


def validate_uuid(value: str) -> bool:
    """Validate that a string is a valid UUID.

    Args:
        value: String to validate.

    Returns:
        True if valid UUID, False otherwise.
    """
    if not value:
        return False

    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def validate_document_id(document_id: str) -> bool:
    """Validate a document ID.

    Document IDs can be UUIDs or MongoDB ObjectIds.

    Args:
        document_id: Document ID to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not document_id:
        return False

    # Check if valid UUID
    if validate_uuid(document_id):
        return True

    # Check if valid MongoDB ObjectId (24 hex characters)
    if re.match(r"^[0-9a-fA-F]{24}$", document_id):
        return True

    return False


def validate_workspace_id(workspace_id: str) -> bool:
    """Validate a workspace ID.

    Workspace IDs are typically MongoDB ObjectIds.

    Args:
        workspace_id: Workspace ID to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not workspace_id:
        return False

    # Check if valid UUID
    if validate_uuid(workspace_id):
        return True

    # Check if valid MongoDB ObjectId (24 hex characters)
    if re.match(r"^[0-9a-fA-F]{24}$", workspace_id):
        return True

    return False


def sanitize_string(value: str, max_length: int = 255) -> str:
    """Sanitize a general string input.

    - Strips whitespace
    - Removes control characters
    - Truncates to max length

    Args:
        value: String to sanitize.
        max_length: Maximum length. Default 255.

    Returns:
        Sanitized string.
    """
    if not value:
        return ""

    # Normalize unicode
    value = unicodedata.normalize("NFC", value)

    # Remove control characters
    value = "".join(
        char for char in value if not unicodedata.category(char).startswith("C") or char in "\n\t"
    )

    # Strip whitespace
    value = value.strip()

    # Truncate
    if len(value) > max_length:
        value = value[:max_length]

    return value


def is_safe_path(path: str) -> bool:
    """Check if a path is safe (no directory traversal).

    Args:
        path: Path to check.

    Returns:
        True if safe, False if contains traversal attempts.
    """
    if not path:
        return False

    # Check for directory traversal
    if ".." in path:
        return False

    # Check for absolute paths
    if path.startswith("/") or path.startswith("\\"):
        return False

    # Check for Windows drive letters
    if re.match(r"^[a-zA-Z]:", path):
        return False

    return True
