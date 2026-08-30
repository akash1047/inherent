"""Minimal authenticated HTTP client and shared error translation."""

from __future__ import annotations

from typing import Any

import click
import httpx

from inh_cli.config import Resolved


class ClientError(click.ClickException):
    """A user-facing API failure with its CLI exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        # Click declares this on the class but reads an instance override.
        setattr(self, "exit_code", exit_code)


def make_client(
    resolved: Resolved, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """Create an authenticated client for one resolved stack."""

    headers = {"X-API-Key": resolved.api_key}
    if resolved.workspace_id:
        headers["X-Workspace-Id"] = resolved.workspace_id
    return httpx.Client(base_url=resolved.url, headers=headers, transport=transport)


def request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Make a request and translate transport and HTTP failures once."""

    try:
        response = client.request(method, path, **kwargs)
    except httpx.ConnectError as error:
        raise ClientError(
            f"No stack reachable at {client.base_url}. Run `inherent up` and try again.",
            exit_code=2,
        ) from error

    if response.status_code in (401, 403):
        raise ClientError("API key rejected. Check INHERENT_API_KEY or reconnect this CLI.")
    if response.is_error:
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        if content_type == "application/problem+json":
            try:
                problem = response.json()
            except ValueError as error:
                raise ClientError(
                    f"HTTP {response.status_code}: invalid problem response"
                ) from error
            title = problem.get("title", f"HTTP {response.status_code}")
            detail = problem.get("detail")
            raise ClientError(f"{title}: {detail}" if detail else str(title))
        raise ClientError(f"HTTP {response.status_code}: {response.reason_phrase}")
    return response
