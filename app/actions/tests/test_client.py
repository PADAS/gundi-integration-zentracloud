import datetime

import httpx
import pytest
import stamina

from app.actions.client import (
    verify_credentials,
    raise_for_readings_status,
    ZentraCloudUnauthorizedException,
    PullObservationsBadConfigException,
    ZentraCloudResponse,
)
from app.actions.configurations import AuthenticateConfig


def _resp(status):
    return httpx.Response(status, request=httpx.Request("GET", "https://zentracloud.com/api/v4/get_readings/"))


def test_non_retryable_errors_are_not_httpx_errors():
    # The pull retries on=httpx.HTTPError, so for an error to fail fast it must
    # NOT be an httpx error. This is what makes 4xx skip the retry loop.
    assert not issubclass(ZentraCloudUnauthorizedException, httpx.HTTPError)
    assert not issubclass(PullObservationsBadConfigException, httpx.HTTPError)


def test_readings_status_ok_does_not_raise():
    raise_for_readings_status(_resp(200))


@pytest.mark.parametrize("status", [401, 403])
def test_readings_status_auth_errors_are_non_retryable(status):
    with pytest.raises(ZentraCloudUnauthorizedException):
        raise_for_readings_status(_resp(status))


@pytest.mark.parametrize("status", [400, 404, 422])
def test_readings_status_other_4xx_are_non_retryable(status):
    with pytest.raises(PullObservationsBadConfigException):
        raise_for_readings_status(_resp(status))


@pytest.mark.parametrize("status", [429, 500, 503])
def test_readings_status_transient_raise_httpx_error(status):
    # 5xx / 429 stay retryable (httpx.HTTPError), so stamina keeps retrying them.
    with pytest.raises(httpx.HTTPError):
        raise_for_readings_status(_resp(status))


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    ZentraCloudUnauthorizedException(message="x", status_code=401),
    PullObservationsBadConfigException(message="bad", status_code=400),
])
async def test_non_retryable_errors_fail_after_single_attempt(exc):
    attempts = 0
    with pytest.raises(type(exc)):
        async for attempt in stamina.retry_context(
            on=httpx.HTTPError, attempts=3,
            wait_initial=datetime.timedelta(0), wait_max=datetime.timedelta(0),
        ):
            with attempt:
                attempts += 1
                raise exc
    assert attempts == 1


@pytest.mark.asyncio
async def test_transient_httpx_error_is_retried_three_times():
    attempts = 0
    with pytest.raises(httpx.HTTPError):
        async for attempt in stamina.retry_context(
            on=httpx.HTTPError, attempts=3,
            wait_initial=datetime.timedelta(0), wait_max=datetime.timedelta(0),
        ):
            with attempt:
                attempts += 1
                raise httpx.ConnectError("boom")
    assert attempts == 3


def _response_with(readings):
    return ZentraCloudResponse.parse_obj({
        "pagination": {
            "page_num_readings": 1,
            "page_start_date": "2026-06-20T10:00:00+00:00",
            "page_end_date": "2026-06-20T10:00:00+00:00",
        },
        "readings": readings,
    })


def test_response_parses_when_device_omits_some_sensor_types():
    # Regression: a weather station (z6-27505) reports only a subset of sensors;
    # absent sensor types must not raise "field required".
    resp = _response_with({
        "Air Temperature": [{"readings": [{
            "datetime": "2026-06-20 10:00:00+0000",
            "value": 21.5, "precision": 1, "mrid": 1, "error_flag": False,
        }]}],
    })
    assert resp.readings["Air Temperature"][0].readings[0].value == 21.5
    # Sensors the device doesn't have are simply absent, not a validation error.
    assert "Soil Temperature" not in resp.readings


def test_response_keeps_unknown_sensor_types():
    # Open dict: a measurement name not in the old hardcoded list is retained,
    # not silently dropped.
    resp = _response_with({
        "Brand New Sensor": [{"readings": [{
            "datetime": "2026-06-20 10:00:00+0000",
            "value": 7.0, "precision": 1, "mrid": 9, "error_flag": False,
        }]}],
    })
    assert "Brand New Sensor" in resp.readings
    assert resp.readings["Brand New Sensor"][0].readings[0].value == 7.0


def make_config(token="abc123", api_url="https://zentracloud.com"):
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
        make_config(token="abc123", api_url="https://tahmo.zentracloud.com"),
        session=session,
    )
    assert captured["auth"] == "Token abc123"
    assert captured["url"].startswith("https://tahmo.zentracloud.com/api/v4/get_readings/")
