import pytest
import pydantic

from app.actions.configurations import PullObservationsConfig


def test_pull_observations_config_exposes_api_url():
    config = PullObservationsConfig.parse_obj({
        "api_url": "https://zentracloud.com/api/v4/get_readings/",
        "devices_serial_number": ["z6-27505"],
    })

    assert str(config.api_url) == "https://zentracloud.com/api/v4/get_readings/"


def test_pull_observations_config_rejects_empty_api_url():
    # Regression: an empty URL previously reached httpx and raised a cryptic
    # UnsupportedProtocol error after wasting retries. It must fail validation.
    with pytest.raises(pydantic.ValidationError):
        PullObservationsConfig.parse_obj({
            "api_url": "",
            "devices_serial_number": ["z6-27505"],
        })


def test_pull_observations_config_rejects_url_without_scheme():
    with pytest.raises(pydantic.ValidationError):
        PullObservationsConfig.parse_obj({
            "api_url": "zentracloud.com/api/v4/get_readings/",
            "devices_serial_number": ["z6-27505"],
        })
