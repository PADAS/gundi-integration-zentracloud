from typing import List
from pydantic import SecretStr, Field

from .core import AuthActionConfiguration, PullActionConfiguration


class AuthenticateConfig(AuthActionConfiguration):
    token: SecretStr


class PullObservationsConfig(PullActionConfiguration):
    devices_serial_number: List[str] = Field(
        ...,
        title="Devices by Serial Number",
        description="List device serial numbers to fetch data from Zentra Cloud"
    )

    devices_per_page: int = 1000
