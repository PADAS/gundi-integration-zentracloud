import pytest
import pydantic

from app.actions.configurations import AuthenticateConfig


def test_authenticate_config_exposes_api_url():
    config = AuthenticateConfig.parse_obj({
        "token": "Token abc123",
        "api_url": "https://zentracloud.com/api/v4/get_readings/",
    })

    assert str(config.api_url) == "https://zentracloud.com/api/v4/get_readings/"


def test_authenticate_config_rejects_empty_api_url():
    # Regression: an empty URL previously reached httpx and raised a cryptic
    # UnsupportedProtocol error after wasting retries. It must fail validation.
    with pytest.raises(pydantic.ValidationError):
        AuthenticateConfig.parse_obj({
            "token": "Token abc123",
            "api_url": "",
        })


def test_authenticate_config_rejects_url_without_scheme():
    with pytest.raises(pydantic.ValidationError):
        AuthenticateConfig.parse_obj({
            "token": "Token abc123",
            "api_url": "zentracloud.com/api/v4/get_readings/",
        })
