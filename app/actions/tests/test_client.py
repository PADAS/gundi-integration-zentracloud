import httpx
import pytest

from app.actions.client import (
    verify_credentials,
    ZentraCloudUnauthorizedException,
    ZentraCloudResponse,
)
from app.actions.configurations import AuthenticateConfig


def test_response_parses_when_device_omits_some_sensor_types():
    # Regression: a weather station (z6-27505) reports only a subset of sensors;
    # absent sensor types must not raise "field required".
    resp = ZentraCloudResponse.parse_obj({
        "pagination": {
            "page_num_readings": 1,
            "page_start_date": "2026-06-20T10:00:00+00:00",
            "page_end_date": "2026-06-20T10:00:00+00:00",
        },
        "readings": {
            "Air Temperature": [{"readings": [{
                "datetime": "2026-06-20 10:00:00+0000",
                "value": 21.5, "precision": 1, "mrid": 1, "error_flag": False,
            }]}],
        },
    })
    assert resp.readings.air_temperature[0].readings[0].value == 21.5
    # Sensors the device doesn't have default to empty, not a validation error.
    assert resp.readings.soil_temperature == []
    assert resp.readings.water_content == []
    assert resp.readings.saturation_extract_ec == []


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
