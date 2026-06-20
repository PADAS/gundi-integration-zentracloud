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


# Choices rendered as an inline JSON-schema enum (value -> label). The Gundi
# portal does not dereference $ref, so a Pydantic Enum-typed field (which emits
# allOf/$ref) won't render as a choice control. A plain str field with an inline
# `enum` renders as a select, while the validator below keeps the value
# constrained to the known servers server-side.
SERVER_LABELS = {
    ZentraCloudServer.US.value: "ZentraCloud US",
    ZentraCloudServer.EU.value: "ZentraCloud EU",
    ZentraCloudServer.TAHMO.value: "TAHMO",
}


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
        if value not in SERVER_LABELS:
            raise ValueError(
                f"api_url must be one of the known ZentraCloud servers: "
                f"{', '.join(SERVER_LABELS)}"
            )
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
