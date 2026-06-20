import pytest
import pydantic

from app.actions.configurations import AuthenticateConfig, ZentraCloudServer


def test_authenticate_config_defaults_to_us_server():
    config = AuthenticateConfig.parse_obj({"token": "Token abc123"})

    assert config.api_url == ZentraCloudServer.US
    assert config.api_url == "https://zentracloud.com/api/v4/get_readings/"


def test_authenticate_config_accepts_tahmo_server():
    config = AuthenticateConfig.parse_obj({
        "token": "Token abc123",
        "api_url": "https://tahmo.zentracloud.com/api/v4/get_readings/",
    })

    assert config.api_url == ZentraCloudServer.TAHMO


def test_authenticate_config_accepts_arbitrary_url():
    # Free-text field: any valid http(s) URL is accepted (e.g. a server not in
    # the predefined list). Constraint is only that it is a real URL.
    config = AuthenticateConfig.parse_obj({
        "token": "Token abc123",
        "api_url": "https://example.com/api/v4/get_readings/",
    })

    assert config.api_url == "https://example.com/api/v4/get_readings/"


def test_authenticate_config_rejects_empty_api_url():
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


def test_auth_header_normalizes_token_without_prefix():
    config = AuthenticateConfig.parse_obj({"token": "abc123"})
    assert config.auth_header == "Token abc123"


def test_auth_header_does_not_double_token_prefix():
    # Portal credentials are sometimes stored already including "Token ".
    # The header must contain exactly one prefix, not "Token Token abc123".
    config = AuthenticateConfig.parse_obj({"token": "Token abc123"})
    assert config.auth_header == "Token abc123"


def test_auth_header_strips_surrounding_whitespace():
    config = AuthenticateConfig.parse_obj({"token": "  Token abc123  "})
    assert config.auth_header == "Token abc123"


def test_server_enum_has_three_known_servers():
    assert {s.value for s in ZentraCloudServer} == {
        "https://zentracloud.com/api/v4/get_readings/",
        "https://zentracloud.eu/api/v4/get_readings/",
        "https://tahmo.zentracloud.com/api/v4/get_readings/",
    }
