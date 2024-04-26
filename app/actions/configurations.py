from typing import List
from .core import ActionConfiguration


class AuthenticateConfig(ActionConfiguration):
    token: str


class PullObservationsConfig(ActionConfiguration):
    devices_serial_number: List[str]
    devices_per_page: int = 1000
