import httpx
import pytest

from app.actions import handlers
from app.actions.client import ZentraCloudUnauthorizedException
from app.actions.configurations import AuthenticateConfig


class FakeIntegration:
    id = "5185abb5-46ee-41cf-bbe1-d691dd314fc5"


def make_config():
    return AuthenticateConfig.parse_obj({
        "token": "Token abc123",
        "api_url": "https://tahmo.zentracloud.com/api/v4/get_readings/",
    })


@pytest.mark.asyncio
async def test_action_auth_reports_valid_credentials(mocker):
    verify = mocker.patch.object(handlers.client, "verify_credentials", new_callable=mocker.AsyncMock)
    verify.return_value = True

    result = await handlers.action_auth(FakeIntegration(), make_config())

    assert result["valid_credentials"] is True
    verify.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_auth_reports_invalid_credentials_on_401(mocker):
    verify = mocker.patch.object(handlers.client, "verify_credentials", new_callable=mocker.AsyncMock)
    verify.side_effect = ZentraCloudUnauthorizedException(message="Invalid token.", status_code=401)

    result = await handlers.action_auth(FakeIntegration(), make_config())

    assert result["valid_credentials"] is False
    assert result["status_code"] == 401


@pytest.mark.asyncio
async def test_action_auth_raises_on_transport_error(mocker):
    verify = mocker.patch.object(handlers.client, "verify_credentials", new_callable=mocker.AsyncMock)
    verify.side_effect = httpx.ConnectError("no route to host")

    with pytest.raises(httpx.HTTPError):
        await handlers.action_auth(FakeIntegration(), make_config())
