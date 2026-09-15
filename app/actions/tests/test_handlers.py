import httpx
import pytest

from app.actions import handlers
from app.actions.client import ZentraCloudUnauthorizedException, ZentraCloudResponse
from app.actions.configurations import AuthenticateConfig, DeviceLocation, PullObservationsConfig


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
        "token": "abc123",
        "api_url": "https://tahmo.zentracloud.com",
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


class _PullCfg:
    def __init__(self, devices):
        self.devices_serial_number = devices
        self.devices_per_page = 1000

    def dict(self):
        return {"devices_serial_number": self.devices_serial_number, "devices_per_page": self.devices_per_page}

    def location_for(self, serial_number):
        return None


def _patch_pull_deps(mocker, *, devices, returned):
    # Silence the activity_logger decorator's pubsub publishes.
    mocker.patch("app.services.activity_logger.publish_event", new_callable=mocker.AsyncMock)
    mocker.patch.object(handlers.client, "get_auth_config", return_value=object())
    mocker.patch.object(handlers.client, "get_pull_observations_config", return_value=_PullCfg(devices))
    mocker.patch.object(
        handlers.client, "get_readings_endpoint_response",
        new_callable=mocker.AsyncMock, return_value={d: object() for d in returned},
    )
    # Isolate the summary logic from the transform/send path.
    mocker.patch.object(handlers, "filter_and_transform", new_callable=mocker.AsyncMock, return_value=[])
    return mocker.patch.object(handlers, "log_action_activity", new_callable=mocker.AsyncMock)


@pytest.mark.asyncio
async def test_pull_logs_one_collapsed_summary_for_rate_limited_devices(mocker):
    # Two of three devices were dropped by the client (persistent 429). We expect
    # exactly ONE summary activity log naming them — not one error per device.
    devices = ["z6-1", "z6-2", "z6-3"]
    summary = _patch_pull_deps(mocker, devices=devices, returned=["z6-1"])

    await handlers.action_pull_observations(
        integration=FakeIntegration(), action_config=_PullCfg(devices)
    )

    summary.assert_awaited_once()
    kwargs = summary.await_args.kwargs
    assert kwargs["level"] == "INFO"
    assert sorted(kwargs["data"]["rate_limited_devices"]) == ["z6-2", "z6-3"]


@pytest.mark.asyncio
async def test_pull_logs_no_summary_when_all_devices_returned(mocker):
    # No device was rate-limited → no summary activity log at all.
    devices = ["z6-1", "z6-2"]
    summary = _patch_pull_deps(mocker, devices=devices, returned=devices)

    await handlers.action_pull_observations(
        integration=FakeIntegration(), action_config=_PullCfg(devices)
    )

    summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_filter_and_transform_uses_configured_device_location(mocker):
    mocker.patch.object(handlers.state_manager, "get_state", new_callable=mocker.AsyncMock, return_value=None)
    location = DeviceLocation(serial_number="z6-27505", lat=36.9060639, lon=-121.8430089)

    result = await handlers.filter_and_transform(
        "z6-27505", make_readings(), "intid", "pull_observations", device_location=location
    )

    assert result[0]["location"] == {"lat": 36.9060639, "lon": -121.8430089}


@pytest.mark.asyncio
async def test_filter_and_transform_defaults_to_null_island_without_location(mocker):
    mocker.patch.object(handlers.state_manager, "get_state", new_callable=mocker.AsyncMock, return_value=None)

    result = await handlers.filter_and_transform("z6-27505", make_readings(), "intid", "pull_observations")

    # Backward compatible: devices without a configured location keep 0,0.
    assert result[0]["location"] == {"lat": 0.0, "lon": 0.0}


def test_pull_config_location_for_matches_by_serial():
    config = PullObservationsConfig.parse_obj({
        "devices_serial_number": ["z6-1", "z6-2"],
        "devices_location": [{"serial_number": "z6-1", "lat": 36.9, "lon": -121.8}],
    })
    assert config.location_for("z6-1").lat == 36.9
    assert config.location_for("z6-2") is None
