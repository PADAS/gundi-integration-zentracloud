from enum import Enum
from typing import List
from pydantic import SecretStr, Field, validator

from app.services.utils import FieldWithUIOptions, UIOptions, GlobalUISchemaOptions
from .core import AuthActionConfiguration, PullActionConfiguration, ExecutableActionMixin


class ZentraCloudServer(str, Enum):
    # ZentraCloud's regional servers. Each is paired with its own account token,
    # so the choice lives with the credentials. Stored as the server base only;
    # the get_readings path is appended by the client (see readings_url).
    US = "https://zentracloud.com"
    EU = "https://zentracloud.eu"
    TAHMO = "https://tahmo.zentracloud.com"


# Rendered as an inline JSON-schema enum (value -> label). The Gundi portal does
# not dereference $ref, so a plain str field with an inline `enum` is used (a
# Pydantic Enum-typed field would emit allOf/$ref and not render as a select).
SERVER_LABELS = {
    ZentraCloudServer.US.value: "ZentraCloud US",
    ZentraCloudServer.EU.value: "ZentraCloud EU",
    ZentraCloudServer.TAHMO.value: "TAHMO",
}

# Path appended to the selected server to reach the readings endpoint.
READINGS_PATH = "api/v4/get_readings/"


class AuthenticateConfig(AuthActionConfiguration, ExecutableActionMixin):
    token: SecretStr = FieldWithUIOptions(
        ...,
        title="Token",
        description="Your ZentraCloud API token (just the token value, without a 'Token ' prefix).",
        ui_options=UIOptions(
            widget="password",
        ),
    )
    api_url: str = FieldWithUIOptions(
        ZentraCloudServer.US.value,
        title="API URL",
        description="ZentraCloud server hosting your devices.",
        enum=list(SERVER_LABELS.keys()),
        ui_options=UIOptions(
            widget="select",
            enumNames=list(SERVER_LABELS.values()),
        ),
    )

    ui_global_options = GlobalUISchemaOptions(
        order=["api_url", "token"],
    )

    @validator("api_url")
    def api_url_must_be_known_server(cls, value):
        server = value.rstrip("/")
        # Tolerate a previously-stored full readings URL by reducing it to the
        # server base, so existing integrations keep working until re-selected.
        suffix = "/" + READINGS_PATH.strip("/")
        if server.endswith(suffix):
            server = server[: -len(suffix)]
        if server not in SERVER_LABELS:
            raise ValueError(
                f"api_url must be one of the known ZentraCloud servers: "
                f"{', '.join(SERVER_LABELS)}"
            )
        return server

    @property
    def readings_url(self) -> str:
        # The user selects only the server; append the get_readings path here.
        return f"{self.api_url.rstrip('/')}/{READINGS_PATH}"

    @property
    def auth_header(self) -> str:
        # ZentraCloud expects "Authorization: Token <token>". Users enter just
        # the token value; we add the prefix here. A stray "Token " prefix is
        # tolerated to avoid a "Token Token ..." 401.
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
