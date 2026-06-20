import httpx
import pytest

from app.actions import handlers
from app.actions.client import ZentraCloudUnauthorizedException, ZentraCloudResponse
from app.actions.configurations import AuthenticateConfig


def make_readings(extra=None):
    readings = {
        "Air Temperature": [{"readings": [{
            "datetime": "2026-06-20 10:00:00+0000",
            "value": 21.5, "precision": 1, "mrid": 1, "error_flag": False,
        }]}],
        "Battery Percent": [{"readings": [{
            "datetime": "2026-06-20 10:00:00+0000",
            "value": 90, "precision": 0, "mrid": 2, "error_flag": False,
        }]}],
    }
    if extra:
        readings.update(extra)
    return ZentraCloudResponse.parse_obj({
        "pagination": {
            "page_num_readings": 1,
            "page_start_date": "2026-06-20T10:00:00+00:00",
            "page_end_date": "2026-06-20T10:00:00+00:00",
        },
        "readings": readings,
    })


@pytest.mark.asyncio
async def test_filter_and_transform_with_missing_sensors(mocker):
    mocker.patch.object(handlers.state_manager, "get_state", new_callable=mocker.AsyncMock, return_value=None)

    result = await handlers.filter_and_transform("z6-27505", make_readings(), "intid", "pull_observations")

    assert len(result) == 1
    obs = result[0]
    assert obs["source"] == "z6-27505"
    assert obs["additional"]["air_temperature_value"] == 21.5
    assert obs["additional"]["battery_percent_value"] == 90
    # No keys for sensors the device didn't report.
    assert not any(k.startswith("soil_temperature_") for k in obs["additional"])


@pytest.mark.asyncio
async def test_filter_and_transform_keeps_unknown_sensors(mocker):
    mocker.patch.object(handlers.state_manager, "get_state", new_callable=mocker.AsyncMock, return_value=None)
    readings = make_readings(extra={
        "Brand New Sensor": [{"readings": [{
            "datetime": "2026-06-20 10:00:00+0000",
            "value": 7.0, "precision": 1, "mrid": 9, "error_flag": False,
        }]}],
    })

    result = await handlers.filter_and_transform("z6-27505", readings, "intid", "pull_observations")

    # Unknown measurement names are normalized to snake_case keys, not dropped.
    assert result[0]["additional"]["brand_new_sensor_value"] == 7.0


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
