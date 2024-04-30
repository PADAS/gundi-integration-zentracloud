from typing import List
from .core import AuthActionConfiguration, PullActionConfiguration


class AuthenticateConfig(AuthActionConfiguration):
    token: str


class PullObservationsConfig(PullActionConfiguration):
    devices_serial_number: List[str]
    devices_per_page: int = 1000
