from enum import Enum
from typing import List
from pydantic import SecretStr, Field, validator

from app.services.utils import FieldWithUIOptions, UIOptions, GlobalUISchemaOptions
from .core import AuthActionConfiguration, PullActionConfiguration


class ZentraCloudServer(str, Enum):
    # ZentraCloud's regional get_readings endpoints. Each server is paired with
    # its own account token, so the choice lives with the credentials.
    US = "https://zentracloud.com/api/v4/get_readings/"
    EU = "https://zentracloud.eu/api/v4/get_readings/"
    TAHMO = "https://tahmo.zentracloud.com/api/v4/get_readings/"


# Default endpoint. ZentraCloud has regional servers (US: zentracloud.com,
# EU: zentracloud.eu, TAHMO: tahmo.zentracloud.com), each at /api/v4/get_readings/.
# Rendered as a free-text field: an inline-enum/radio choice control does not
# survive Gundi's action-schema registration, so the server is entered as text.
DEFAULT_API_URL = ZentraCloudServer.US.value


class AuthenticateConfig(AuthActionConfiguration):
    token: SecretStr = FieldWithUIOptions(
        ...,
        title="Token",
        description="ZentraCloud API token.",
        ui_options=UIOptions(
            widget="password",
        ),
    )
    api_url: str = FieldWithUIOptions(
        DEFAULT_API_URL,
        title="API URL",
        description=(
            "ZentraCloud get_readings endpoint for the server hosting your devices. "
            "US: https://zentracloud.com/api/v4/get_readings/, "
            "EU: https://zentracloud.eu/api/v4/get_readings/, "
            "TAHMO: https://tahmo.zentracloud.com/api/v4/get_readings/"
        ),
    )

    ui_global_options = GlobalUISchemaOptions(
        order=["api_url", "token"],
    )

    @validator("api_url")
    def api_url_must_have_scheme(cls, value):
        if not value.startswith(("http://", "https://")):
            raise ValueError("api_url must start with 'http://' or 'https://'")
        return value

    @property
    def auth_header(self) -> str:
        # ZentraCloud expects "Authorization: Token <token>". The token is
        # sometimes entered in the portal already including the "Token " prefix,
        # so normalize to exactly one prefix to avoid a "Token Token ..." 401.
        token = self.token.get_secret_value().strip()
        if token.lower().startswith("token "):
            token = token.split(" ", 1)[1].strip()
        return f"Token {token}"


class PullObservationsConfig(PullActionConfiguration):
    devices_serial_number: List[str] = Field(
        ...,
        title="Devices by Serial Number",
        description="List device serial numbers to fetch data from Zentra Cloud"
    )

    devices_per_page: int = 1000
