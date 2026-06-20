import logging
import pydantic
import httpx

from app.actions.configurations import *
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

from app.services.errors import ConfigurationNotFound
from app.services.utils import find_config_for_action
from app.services.state import IntegrationStateManager


logger = logging.getLogger(__name__)
state_manager = IntegrationStateManager()

USER_GET_OBJECTS = "USER_GET_OBJECTS"
USER_GET_STATUS = "USER_GET_STATUS"


# Pydantic Models
class ReadingData(pydantic.BaseModel):
    reading_datetime: str = pydantic.Field(..., alias="datetime")
    value: Optional[float]
    precision: int
    mrid: int
    error_flag: bool
    error_description: Optional[str] = ""


class Reading(pydantic.BaseModel):
    readings: List[ReadingData]


class PaginationData(pydantic.BaseModel):
    page_num_readings: int
    page_start_date: datetime
    page_end_date: datetime


class ZentraCloudResponse(pydantic.BaseModel):
    pagination: PaginationData
    # ZentraCloud returns measurements keyed by name (e.g. "Air Temperature"),
    # and each device only includes the sensors it actually has. Model it as an
    # open dict so any sensor set — including ones we haven't seen before — is
    # accepted and preserved rather than dropped.
    readings: Dict[str, List[Reading]]


class PullObservationsBadConfigException(Exception):
    def __init__(self, message: str, status_code=422):
        self.status_code = status_code
        self.message = message
        super().__init__(f'{self.status_code}: {self.message}')


class ZentraCloudUnauthorizedException(Exception):
    def __init__(self, message: str, status_code=401):
        self.status_code = status_code
        self.message = message
        super().__init__(f'{self.status_code}: {self.message}')


def raise_for_readings_status(response):
    """Raise for an error response, distinguishing retryable from non-retryable.

    The pull is wrapped in stamina.retry_context(on=httpx.HTTPError), so:
    - 5xx / 429 are transient -> raise an httpx error (retried).
    - 4xx are client errors that won't fix themselves -> raise a non-httpx
      exception so the retry loop is skipped and we fail fast (GUNDI-5425).
    """
    status = response.status_code
    if status < 400:
        return
    if status == 429 or status >= 500:
        response.raise_for_status()  # httpx.HTTPStatusError -> retryable
    if status in (401, 403):
        raise ZentraCloudUnauthorizedException(
            message=f"ZentraCloud rejected the credentials (HTTP {status}).",
            status_code=status,
        )
    raise PullObservationsBadConfigException(
        message=f"ZentraCloud returned HTTP {status} for the readings request.",
        status_code=status,
    )


def get_auth_config(integration):
    # Look for the login credentials, needed for any action
    auth_config = find_config_for_action(
        configurations=integration.configurations,
        action_id="auth"
    )
    if not auth_config:
        raise ConfigurationNotFound(
            f"Authentication settings for integration {str(integration.id)} "
            f"are missing. Please fix the integration setup in the portal."
        )
    return AuthenticateConfig.parse_obj(auth_config.data)


def get_pull_observations_config(integration):
    # Look for the login credentials, needed for any action
    config = find_config_for_action(
        configurations=integration.configurations,
        action_id="pull_observations"
    )
    if not config:
        raise ConfigurationNotFound(
            f"PullObservations settings for integration {str(integration.id)} "
            f"are missing. Please fix the integration setup in the portal."
        )
    return PullObservationsConfig.parse_obj(config.data)


async def verify_credentials(auth_config, session=None):
    """Check that the token is accepted by the chosen ZentraCloud server.

    Makes a minimal request to the configured get_readings endpoint. The
    endpoint requires a device_sn, so a valid token without one returns a 4xx
    that is NOT 401/403 — that still proves the credentials were accepted. Only
    401/403 mean the token was rejected.

    Returns True on success; raises ZentraCloudUnauthorizedException on 401/403.
    Connection/transport errors propagate as httpx exceptions.
    """
    owns_session = session is None
    if owns_session:
        session = httpx.AsyncClient(timeout=120)
    try:
        response = await session.get(
            auth_config.readings_url,
            params={"per_page": 1},
            headers={"Authorization": auth_config.auth_header},
        )
    finally:
        if owns_session:
            await session.aclose()

    if response.status_code in (401, 403):
        raise ZentraCloudUnauthorizedException(
            message=f"ZentraCloud rejected the credentials for {auth_config.api_url} "
                    f"(HTTP {response.status_code}).",
            status_code=response.status_code,
        )
    return True


async def get_readings_endpoint_response(integration, auth_config, config):
    readings_per_device = {}
    try:
        url = auth_config.readings_url

        for device in config.devices_serial_number:
            # Get current state for the device
            current_state = await state_manager.get_state(
                str(integration.id),
                "pull_observations",
                device
            )

            if current_state:
                latest_device_timestamp = datetime.strptime(
                    current_state.get("latest_device_timestamp"),
                    '%Y-%m-%d %H:%M:%S%z'
                ).strftime('%Y-%m-%d %H:%M')
            else:
                latest_device_timestamp = (
                        datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=1)
                ).strftime('%Y-%m-%d %H:%M')

            # Request params
            params = {
                "device_sn": device,
                "per_page": config.devices_per_page,
                "start_date": latest_device_timestamp
            }

            async with httpx.AsyncClient(timeout=120) as session:
                response = await session.get(
                    url,
                    params=params,
                    headers={'Authorization': auth_config.auth_header}
                )
                raise_for_readings_status(response)

            response = response.json()

            readings = ZentraCloudResponse.parse_obj({
                "pagination": response.get("pagination"),
                "readings": response.get("data")
            })

            readings_per_device[device] = readings

    except pydantic.ValidationError as ve:
        message = f'Error while parsing ZentraCloud READINGS endpoint. {ve.json()}'
        logger.exception(
            message,
            extra={
                "integration_id": str(integration.id),
                "attention_needed": True
            }
        )
        raise ve

    except Exception as e:
        message = f"Unhandled exception occurred. Exception: {e}"
        logger.exception(
            message,
            extra={
                "integration_id": str(integration.id),
                "attention_needed": True
            }
        )
        raise e

    return readings_per_device
