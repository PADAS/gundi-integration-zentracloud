import pytest
import pydantic

from app.actions.configurations import AuthenticateConfig, ZentraCloudServer
from app.actions.core import ExecutableActionMixin


def test_auth_config_is_executable():
    # self_registration sets action_schema["is_executable"]=True for
    # ExecutableActionMixin subclasses, which makes the portal render the
    # "Test" button so the credential check can be triggered on demand.
    assert issubclass(AuthenticateConfig, ExecutableActionMixin)


def test_api_url_is_the_server_only():
    # The user selects only the server; the path is not part of the config.
    config = AuthenticateConfig.parse_obj({"token": "abc123"})
    assert config.api_url == ZentraCloudServer.US
    assert config.api_url == "https://zentracloud.com"


def test_readings_url_appends_path():
    config = AuthenticateConfig.parse_obj({"token": "abc123", "api_url": "https://tahmo.zentracloud.com"})
    assert config.readings_url == "https://tahmo.zentracloud.com/api/v4/get_readings/"


def test_api_url_accepts_each_known_server():
    for server in ZentraCloudServer:
        config = AuthenticateConfig.parse_obj({"token": "abc123", "api_url": server.value})
        assert config.api_url == server


def test_api_url_tolerates_previously_stored_full_url():
    # Existing integrations stored the full readings URL; normalize it to the
    # server base so the running pull doesn't break before re-selection.
    config = AuthenticateConfig.parse_obj({
        "token": "abc123",
        "api_url": "https://tahmo.zentracloud.com/api/v4/get_readings/",
    })
    assert config.api_url == ZentraCloudServer.TAHMO
    assert config.readings_url == "https://tahmo.zentracloud.com/api/v4/get_readings/"


def test_api_url_rejects_unknown_server():
    with pytest.raises(pydantic.ValidationError):
        AuthenticateConfig.parse_obj({"token": "abc123", "api_url": "https://example.com"})


def test_api_url_rejects_empty():
    with pytest.raises(pydantic.ValidationError):
        AuthenticateConfig.parse_obj({"token": "abc123", "api_url": ""})


def test_api_url_renders_as_inline_enum_select():
    prop = AuthenticateConfig.schema()["properties"]["api_url"]
    assert prop.get("enum") == [s.value for s in ZentraCloudServer]
    assert "allOf" not in prop and "$ref" not in prop
    assert AuthenticateConfig.ui_schema()["api_url"]["ui:widget"] == "select"


def test_server_enum_holds_base_urls_without_path():
    assert {s.value for s in ZentraCloudServer} == {
        "https://zentracloud.com",
        "https://zentracloud.eu",
        "https://tahmo.zentracloud.com",
    }


def test_auth_header_adds_prefix_to_raw_token():
    config = AuthenticateConfig.parse_obj({"token": "abc123", "api_url": "https://zentracloud.com"})
    assert config.auth_header == "Token abc123"


def test_auth_header_does_not_double_token_prefix():
    # Defensive: tolerate a token pasted with the prefix still attached.
    config = AuthenticateConfig.parse_obj({"token": "Token abc123", "api_url": "https://zentracloud.com"})
    assert config.auth_header == "Token abc123"


def test_auth_header_strips_surrounding_whitespace():
    config = AuthenticateConfig.parse_obj({"token": "  abc123  ", "api_url": "https://zentracloud.com"})
    assert config.auth_header == "Token abc123"
