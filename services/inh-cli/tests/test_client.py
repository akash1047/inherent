import httpx
import pytest

from inh_cli.client import ClientError, make_client, request
from inh_cli.config import Resolved


def _resolved() -> Resolved:
    return Resolved("http://inherent.test", "ink_test", "ws_test")


def test_client_sets_auth_and_workspace_headers() -> None:
    client = make_client(_resolved())

    assert client.headers["X-API-Key"] == "ink_test"
    assert client.headers["X-Workspace-Id"] == "ws_test"


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_actionable(status: int) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(status, request=req))

    with make_client(_resolved(), transport=transport) as client:
        with pytest.raises(ClientError, match="API key") as error:
            request(client, "GET", "/v1/whoami")

    assert error.value.exit_code == 1


def test_connect_error_reports_no_stack() -> None:
    def unavailable(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with make_client(_resolved(), transport=httpx.MockTransport(unavailable)) as client:
        with pytest.raises(
            ClientError, match="No stack reachable at http://inherent.test"
        ) as error:
            request(client, "GET", "/health")

    assert error.value.exit_code == 2


def test_problem_json_renders_title_and_detail() -> None:
    def problem(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            headers={"content-type": "application/problem+json"},
            json={"title": "Invalid request", "detail": "workspace_id is required"},
            request=req,
        )

    with make_client(_resolved(), transport=httpx.MockTransport(problem)) as client:
        with pytest.raises(ClientError, match="Invalid request: workspace_id is required"):
            request(client, "GET", "/v1/documents")


def test_malformed_problem_response_stays_user_facing() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(
            500,
            headers={"content-type": "application/problem+json"},
            text="not json",
            request=req,
        )
    )

    with make_client(_resolved(), transport=transport) as client:
        with pytest.raises(ClientError, match="HTTP 500: invalid problem response"):
            request(client, "GET", "/v1/documents")


def test_plain_http_error_stays_user_facing() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(500, request=req))

    with make_client(_resolved(), transport=transport) as client:
        with pytest.raises(ClientError, match="HTTP 500: Internal Server Error"):
            request(client, "GET", "/health")
