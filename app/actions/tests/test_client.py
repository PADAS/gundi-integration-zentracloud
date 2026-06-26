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
    _get_device_readings,
    _rate_limit_wait_seconds,
    MAX_RATE_LIMIT_RETRIES,
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


def _session_from_handler(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_rate_limit_wait_prefers_retry_after_header():
    response = httpx.Response(429, headers={"Retry-After": "12"}, json={"detail": "slow down"})
    assert _rate_limit_wait_seconds(response) == 12


def test_rate_limit_wait_parses_lockout_detail():
    # TAHMO's body hint when no Retry-After header is present.
    response = httpx.Response(
        429,
        json={"detail": "Exceeded request limit of 1 call per 60 seconds. Lock out expires in 41 seconds."},
    )
    assert _rate_limit_wait_seconds(response) == 41


def test_rate_limit_wait_falls_back_to_default():
    response = httpx.Response(429, json={"detail": "throttled"})
    assert _rate_limit_wait_seconds(response, default=99) == 99


def test_rate_limit_wait_floors_zero_hint():
    # A "0 seconds" / Retry-After: 0 hint must not produce an instant re-request
    # that wastes a retry; it is floored to MIN_RATE_LIMIT_WAIT_SECONDS.
    from app.actions.client import MIN_RATE_LIMIT_WAIT_SECONDS
    assert _rate_limit_wait_seconds(
        httpx.Response(429, headers={"Retry-After": "0"})
    ) == MIN_RATE_LIMIT_WAIT_SECONDS
    assert _rate_limit_wait_seconds(
        httpx.Response(429, json={"detail": "Lock out expires in 0 seconds."})
    ) == MIN_RATE_LIMIT_WAIT_SECONDS


def test_rate_limit_wait_handles_non_string_detail():
    # A structured (non-string) detail must not raise; fall back to default.
    response = httpx.Response(429, json={"detail": {"code": "throttled"}})
    assert _rate_limit_wait_seconds(response, default=42) == 42


def test_rate_limit_wait_caps_absurd_hint():
    # A bogus/huge hint must not park the action past its execution timeout.
    from app.actions.client import MAX_RATE_LIMIT_WAIT_SECONDS
    assert _rate_limit_wait_seconds(
        httpx.Response(429, json={"detail": "Lock out expires in 99999 seconds."})
    ) == MAX_RATE_LIMIT_WAIT_SECONDS
    assert _rate_limit_wait_seconds(
        httpx.Response(429, headers={"Retry-After": "100000"})
    ) == MAX_RATE_LIMIT_WAIT_SECONDS


@pytest.mark.asyncio
async def test_get_device_readings_waits_then_succeeds_on_429(mocker):
    # First call is throttled, second succeeds: the device must NOT be lost,
    # and we must have honored a wait between the two calls.
    sleep = mocker.patch("app.actions.client.asyncio.sleep", new_callable=mocker.AsyncMock)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"detail": "Lock out expires in 5 seconds."})
        return httpx.Response(200, json={"pagination": {}, "data": {}})

    result = await _get_device_readings(
        url="https://tahmo.zentracloud.com/api/v4/get_readings/",
        params={"device_sn": "z6-27505"},
        headers={"Authorization": "Token abc"},
        integration_id="intid",
        device="z6-27505",
        session=_session_from_handler(handler),
    )

    assert result == {"pagination": {}, "data": {}}
    assert calls["n"] == 2
    sleep.assert_awaited_once()
    # Honors the server's lock-out hint (5s) plus the small buffer.
    assert sleep.await_args.args[0] == 5 + 2


@pytest.mark.asyncio
async def test_get_device_readings_returns_none_when_persistently_429(mocker):
    # A device that never recovers is skipped (None), not raised — so it can't
    # abort the rest of the batch.
    mocker.patch("app.actions.client.asyncio.sleep", new_callable=mocker.AsyncMock)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"detail": "Lock out expires in 60 seconds."})

    result = await _get_device_readings(
        url="https://tahmo.zentracloud.com/api/v4/get_readings/",
        params={"device_sn": "z6-27505"},
        headers={"Authorization": "Token abc"},
        integration_id="intid",
        device="z6-27505",
        session=_session_from_handler(handler),
    )

    assert result is None
    assert calls["n"] == MAX_RATE_LIMIT_RETRIES


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected_exc", [
    (401, ZentraCloudUnauthorizedException),
    (403, ZentraCloudUnauthorizedException),
    (400, PullObservationsBadConfigException),
    (404, PullObservationsBadConfigException),
])
async def test_get_device_readings_fails_fast_on_non_retryable_4xx(mocker, status, expected_exc):
    # Composition with GUNDI-5425: a non-429 4xx is classified by
    # raise_for_readings_status and fails fast (no wait, single attempt).
    sleep = mocker.patch("app.actions.client.asyncio.sleep", new_callable=mocker.AsyncMock)

    with pytest.raises(expected_exc):
        await _get_device_readings(
            url="https://zentracloud.com/api/v4/get_readings/",
            params={"device_sn": "z6-27505"},
            headers={"Authorization": "Token abc"},
            integration_id="intid",
            device="z6-27505",
            session=_session_from_handler(lambda request: httpx.Response(status, json={"detail": "nope"})),
        )
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_device_readings_raises_retryable_on_5xx(mocker):
    # 5xx stays an httpx error so the outer stamina loop keeps retrying it.
    mocker.patch("app.actions.client.asyncio.sleep", new_callable=mocker.AsyncMock)

    with pytest.raises(httpx.HTTPError):
        await _get_device_readings(
            url="https://zentracloud.com/api/v4/get_readings/",
            params={"device_sn": "z6-27505"},
            headers={"Authorization": "Token abc"},
            integration_id="intid",
            device="z6-27505",
            session=_session_from_handler(lambda request: httpx.Response(503, json={"detail": "boom"})),
        )
