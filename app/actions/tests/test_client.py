import httpx
import pytest

from app.actions.client import verify_credentials, ZentraCloudUnauthorizedException
from app.actions.configurations import AuthenticateConfig


def make_config(token="Token abc123", api_url="https://zentracloud.com/api/v4/get_readings/"):
    return AuthenticateConfig.parse_obj({"token": token, "api_url": api_url})


def session_returning(status, json=None):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=json or {}))
    )


@pytest.mark.asyncio
async def test_verify_credentials_true_on_200():
    assert await verify_credentials(make_config(), session=session_returning(200)) is True


@pytest.mark.asyncio
async def test_verify_credentials_true_on_missing_device_sn_4xx():
    # get_readings needs a device_sn; without it a *valid* token returns a 400,
    # which still proves the credentials were accepted.
    assert await verify_credentials(
        make_config(), session=session_returning(400, {"detail": "device_sn required"})
    ) is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_verify_credentials_raises_on_auth_error(status):
    with pytest.raises(ZentraCloudUnauthorizedException):
        await verify_credentials(make_config(), session=session_returning(status, {"detail": "Invalid token."}))


@pytest.mark.asyncio
async def test_verify_credentials_sends_normalized_header_to_chosen_server():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={})

    session = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await verify_credentials(
        make_config(token="Token abc123", api_url="https://tahmo.zentracloud.com/api/v4/get_readings/"),
        session=session,
    )
    assert captured["auth"] == "Token abc123"
    assert captured["url"].startswith("https://tahmo.zentracloud.com/api/v4/get_readings/")
