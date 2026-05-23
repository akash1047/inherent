"""MCP Server implementation for AI agent integration."""

from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp.server import Server
from src.models.api_key import APIKeyInfo
from src.models.search import SearchRequest
from src.services.database import get_database
from src.services.search import get_search_service
from src.utils import get_logger

logger = get_logger(__name__)


def create_mcp_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("inherent-knowledge-base")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List available MCP tools."""
        return [
            Tool(
                name="search_documents",
                description="Search for relevant documents and chunks using semantic search. "
                "Omit workspace_id to search across ALL your workspaces.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "api_key": {
                            "type": "string",
                            "description": "Your Inherent API key",
                        },
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        },
                        "workspace_id": {
                            "type": "string",
                            "description": "Optional: specific workspace to search. If omitted, searches all your workspaces.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 10)",
                            "default": 10,
                        },
                    },
                    "required": ["api_key", "query"],
                },
            ),
            Tool(
                name="get_document_context",
                description="Get the full content of a document for context",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "api_key": {
                            "type": "string",
                            "description": "Your Inherent API key",
                        },
                        "document_id": {
                            "type": "string",
                            "description": "The document ID to retrieve",
                        },
                    },
                    "required": ["api_key", "document_id"],
                },
            ),
            Tool(
                name="list_documents",
                description="List all documents. Omit workspace_id to list from ALL your workspaces.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "api_key": {
                            "type": "string",
                            "description": "Your Inherent API key",
                        },
                        "workspace_id": {
                            "type": "string",
                            "description": "Optional: specific workspace. If omitted, lists from all your workspaces.",
                        },
                        "page": {
                            "type": "integer",
                            "description": "Page number (default: 1)",
                            "default": 1,
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "Items per page (default: 20)",
                            "default": 20,
                        },
                    },
                    "required": ["api_key"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Handle tool calls."""
        try:
            api_key = arguments.get("api_key")
            if not api_key:
                return [TextContent(type="text", text="Error: API key is required")]

            # Validate API key
            database = await get_database()
            key_info = await database.validate_api_key(api_key)

            if not key_info:
                return [TextContent(type="text", text="Error: Invalid or expired API key")]

            if name == "search_documents":
                return await _handle_search(key_info, arguments)
            elif name == "get_document_context":
                return await _handle_get_context(key_info, arguments)
            elif name == "list_documents":
                return await _handle_list_documents(key_info, arguments)
            else:
                return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

        except Exception as e:
            logger.error("MCP tool error", tool=name, error=str(e))
            return [TextContent(type="text", text=f"Error: {str(e)}")]

    return server


async def _get_workspace_ids(
    key_info: APIKeyInfo, requested_workspace_id: str | None
) -> tuple[list[str], str | None]:
    """
    Determine which workspace IDs to use for a query.

    Returns:
        tuple of (workspace_ids list, error message or None)
    """
    database = await get_database()

    if requested_workspace_id:
        # User specified a workspace - verify they have access
        user_workspaces = await database.get_user_workspace_ids(key_info.user_id)
        if requested_workspace_id not in user_workspaces:
            return [], f"Error: You don't have access to workspace '{requested_workspace_id}'"
        return [requested_workspace_id], None
    else:
        # No workspace specified - use all user's workspaces
        user_workspaces = await database.get_user_workspace_ids(key_info.user_id)
        if not user_workspaces:
            return [], "No workspaces found. Upload documents to create a workspace."
        return user_workspaces, None


async def _handle_search(key_info: APIKeyInfo, arguments: dict) -> list[TextContent]:
    """Handle search_documents tool."""
    query = arguments.get("query", "")
    limit = arguments.get("limit", 10)
    requested_workspace_id = arguments.get("workspace_id")

    if not query:
        return [TextContent(type="text", text="Error: Query is required")]

    # Get workspace IDs to search
    workspace_ids, error = await _get_workspace_ids(key_info, requested_workspace_id)
    if error:
        return [TextContent(type="text", text=error)]

    search_service = await get_search_service()

    # Search across all workspaces
    all_results = []
    for workspace_id in workspace_ids:
        request = SearchRequest(query=query, limit=limit)
        response = await search_service.search(workspace_id, key_info.user_id, request)
        # Tag results with workspace_id
        for result in response.results:
            result_dict = {
                "workspace_id": workspace_id,
                "document_id": result.document_id,
                "document_name": result.document_name,
                "content": result.content,
                "score": result.score,
            }
            all_results.append(result_dict)

    # Sort by score and limit
    all_results.sort(key=lambda x: x["score"], reverse=True)
    all_results = all_results[:limit]

    if not all_results:
        workspace_note = (
            f" in workspace '{requested_workspace_id}'"
            if requested_workspace_id
            else " across your workspaces"
        )
        return [TextContent(type="text", text=f"No results found for: {query}{workspace_note}")]

    # Format results
    workspace_note = (
        f" in workspace '{requested_workspace_id}'"
        if requested_workspace_id
        else " across all workspaces"
    )
    result_text = f"Found {len(all_results)} results for '{query}'{workspace_note}:\n\n"
    for i, result in enumerate(all_results, 1):
        result_text += f"**{i}. {result['document_name']}** (score: {result['score']:.2f})\n"
        result_text += (
            f"Document ID: {result['document_id']} | Workspace: {result['workspace_id']}\n"
        )
        content = result["content"]
        result_text += f"```\n{content[:500]}{'...' if len(content) > 500 else ''}\n```\n\n"

    return [TextContent(type="text", text=result_text)]


async def _handle_get_context(key_info: APIKeyInfo, arguments: dict) -> list[TextContent]:
    """Handle get_document_context tool."""
    document_id = arguments.get("document_id", "")

    if not document_id:
        return [TextContent(type="text", text="Error: Document ID is required")]

    database = await get_database()

    # Get document and verify user has access
    document = await database.get_document_by_id(document_id)

    if not document:
        return [TextContent(type="text", text=f"Error: Document '{document_id}' not found")]

    # Verify user has access to this workspace
    user_workspaces = await database.get_user_workspace_ids(key_info.user_id)
    if document.workspace_id not in user_workspaces:
        return [
            TextContent(
                type="text", text=f"Error: You don't have access to document '{document_id}'"
            )
        ]

    chunks = await database.get_document_chunks_by_doc_id(document_id)
    full_text = "\n\n".join(chunk.content for chunk in chunks)

    result_text = f"# {document.name}\n\n"
    result_text += f"**Source:** {document.source_type}\n"
    result_text += f"**Size:** {document.size_bytes:,} bytes\n"
    result_text += f"**Chunks:** {len(chunks)}\n"
    result_text += f"**Workspace:** {document.workspace_id}\n\n"
    result_text += "---\n\n"
    result_text += full_text

    return [TextContent(type="text", text=result_text)]


async def _handle_list_documents(key_info: APIKeyInfo, arguments: dict) -> list[TextContent]:
    """Handle list_documents tool."""
    page = arguments.get("page", 1)
    page_size = arguments.get("page_size", 20)
    requested_workspace_id = arguments.get("workspace_id")

    # Get workspace IDs to list from
    workspace_ids, error = await _get_workspace_ids(key_info, requested_workspace_id)
    if error:
        return [TextContent(type="text", text=error)]

    database = await get_database()

    if requested_workspace_id:
        # Single workspace
        documents, total = await database.get_documents(requested_workspace_id, page, page_size)
    else:
        # Multiple workspaces
        documents, total = await database.get_documents_multi_workspace(
            workspace_ids, page, page_size
        )

    if not documents:
        workspace_note = (
            f" in workspace '{requested_workspace_id}'" if requested_workspace_id else ""
        )
        return [TextContent(type="text", text=f"No documents found{workspace_note}")]

    workspace_note = (
        f" in workspace '{requested_workspace_id}'"
        if requested_workspace_id
        else " across all workspaces"
    )
    result_text = f"Found {total} documents{workspace_note} (showing page {page}):\n\n"
    for doc in documents:
        result_text += f"- **{doc.name}**\n"
        result_text += f"  ID: `{doc.id}`\n"
        result_text += f"  Type: {doc.source_type} | Size: {doc.size_bytes:,} bytes\n"
        result_text += f"  Chunks: {doc.chunk_count} | Status: {doc.status} | Workspace: {doc.workspace_id}\n\n"

    return [TextContent(type="text", text=result_text)]


async def run_mcp_server() -> None:
    """Run the MCP server via stdio."""
    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
