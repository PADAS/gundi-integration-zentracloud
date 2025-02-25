from typing import List
from pydantic import SecretStr

from .core import AuthActionConfiguration, PullActionConfiguration


class AuthenticateConfig(AuthActionConfiguration):
    token: SecretStr


class PullObservationsConfig(PullActionConfiguration):
    devices_serial_number: List[str]
    devices_per_page: int = 1000
