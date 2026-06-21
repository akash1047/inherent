"""REST + MCP contract regression suite (M6 #30).

These tests lock down the *public contract* of the two agent-facing surfaces —
the REST API and the MCP server — so client SDKs and agents do not silently
break when the implementation changes:

- **Response shapes** — every response model keeps its required fields and its
  optional/backward-compatible fields stay omittable.
- **Permissions** — each route / MCP tool requires exactly the documented
  permission; a missing permission is rejected (REST 403 / MCP error) and the
  business logic never runs.
- **Auth** — missing / invalid / expired keys are rejected (REST 401 / MCP
  error).
- **Error shape** — error bodies follow the documented contract (plain
  ``detail`` for auth/not-found ``HTTPException`` paths; RFC 7807
  ``application/problem+json`` for validation and ``InherentAPIError`` paths).

Everything here is OFFLINE: the database / search / MQ layers are mocked and the
app lifespan's DB init is stubbed, exactly like the ``tests/integration`` and
``tests/security`` patterns. No live stack is required.
"""
