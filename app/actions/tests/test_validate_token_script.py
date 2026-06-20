import httpx
import pytest

from scripts.validate_zentracloud_token import interpret_status, validate


# The script answers one question: is the token rejected by the server?
# Exit codes: 0 = token accepted, 1 = token invalid (401/403), 2 = unreachable.

def test_interpret_200_is_success():
    code, _, _ = interpret_status(200, has_device_sn=True)
    assert code == 0


@pytest.mark.parametrize("status", [401, 403])
def test_interpret_auth_errors_fail(status):
    code, _, _ = interpret_status(status, has_device_sn=False)
    assert code == 1


@pytest.mark.parametrize("status", [400, 422])
def test_interpret_missing_device_sn_is_success(status):
    code, _, _ = interpret_status(status, has_device_sn=False)
    assert code == 0


@pytest.mark.parametrize("status", [400, 404, 422])
def test_interpret_non_auth_4xx_with_device_sn_is_success(status):
    # Regression: a valid token with a bad/unknown device_sn must NOT be
    # reported as a token failure. The token was accepted (auth passed).
    code, _, _ = interpret_status(status, has_device_sn=True)
    assert code == 0


def test_interpret_server_error_is_not_token_failure():
    code, symbol, _ = interpret_status(500, has_device_sn=False)
    assert code == 0
    assert symbol == "?"


def test_validate_returns_1_on_401(monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"detail": "Invalid token."})
    ))
    assert validate(token="bad", server="tahmo", device_sn="z6-1", client=client) == 1


def test_validate_returns_0_on_200():
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"pagination": {}, "data": {}})
    ))
    assert validate(token="good", server="us", device_sn="z6-1", client=client) == 0


def test_validate_returns_2_on_connection_error():
    def boom(request):
        raise httpx.ConnectError("no route", request=request)

    client = httpx.Client(transport=httpx.MockTransport(boom))
    assert validate(token="x", server="eu", client=client) == 2
