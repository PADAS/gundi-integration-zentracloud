import pytest
import pydantic

from app.actions.configurations import AuthenticateConfig, ZentraCloudServer
from app.actions.core import ExecutableActionMixin


def test_auth_config_is_executable():
    # self_registration sets action_schema["is_executable"]=True for
    # ExecutableActionMixin subclasses, which makes the portal render the
    # "Test" button so the credential check can be triggered on demand.
    assert issubclass(AuthenticateConfig, ExecutableActionMixin)


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


def test_authenticate_config_rejects_unknown_server():
    # Select list: only the known ZentraCloud servers (US/EU/TAHMO) are valid;
    # an arbitrary URL must be rejected rather than silently used.
    with pytest.raises(pydantic.ValidationError):
        AuthenticateConfig.parse_obj({
            "token": "Token abc123",
            "api_url": "https://example.com/api/v4/get_readings/",
        })


def test_authenticate_config_rejects_empty_api_url():
    with pytest.raises(pydantic.ValidationError):
        AuthenticateConfig.parse_obj({
            "token": "Token abc123",
            "api_url": "",
        })


def test_authenticate_config_renders_as_inline_enum_select():
    # The portal does not dereference $ref, so the choices must be an inline
    # JSON-schema enum (not allOf/$ref from a Pydantic Enum-typed field).
    prop = AuthenticateConfig.schema()["properties"]["api_url"]
    assert prop.get("enum") == [s.value for s in ZentraCloudServer]
    assert "allOf" not in prop and "$ref" not in prop
    assert AuthenticateConfig.ui_schema()["api_url"]["ui:widget"] == "select"


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
