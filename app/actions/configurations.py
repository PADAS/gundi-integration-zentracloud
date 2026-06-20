from typing import List
from pydantic import SecretStr, Field, HttpUrl

from .core import AuthActionConfiguration, PullActionConfiguration


class AuthenticateConfig(AuthActionConfiguration):
    token: SecretStr


class PullObservationsConfig(PullActionConfiguration):
    api_url: HttpUrl = Field(
        "https://zentracloud.com/api/v4/get_readings/",
        title="API URL",
        description="ZentraCloud get_readings endpoint URL. Server-specific "
                    "(e.g. US: zentracloud.com, EU, or the TAHMO server)."
    )

    devices_serial_number: List[str] = Field(
        ...,
        title="Devices by Serial Number",
        description="List device serial numbers to fetch data from Zentra Cloud"
    )

    devices_per_page: int = 1000
