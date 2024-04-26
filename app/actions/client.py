import logging
import pydantic
import httpx

from app.actions.configurations import *
from typing import List, Optional
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


class TahmoWeatherData(pydantic.BaseModel):
    air_temperature: List[Reading] = pydantic.Field(..., alias="Air Temperature")
    atmospheric_pressure: List[Reading] = pydantic.Field(..., alias="Atmospheric Pressure")
    battery_percent: List[Reading] = pydantic.Field(..., alias="Battery Percent")
    battery_voltage: List[Reading] = pydantic.Field(..., alias="Battery Voltage")
    gust_speed: List[Reading] = pydantic.Field(..., alias="Gust Speed")
    lightning_activity: List[Reading] = pydantic.Field(..., alias="Lightning Activity")
    lightning_distance: List[Reading] = pydantic.Field(..., alias="Lightning Distance")
    logger_temperature: List[Reading] = pydantic.Field(..., alias="Logger Temperature")
    max_precip_rate: List[Reading] = pydantic.Field(..., alias="Max Precip Rate")
    precipitation: List[Reading] = pydantic.Field(..., alias="Precipitation")
    rh_sensor_temp: List[Reading] = pydantic.Field(..., alias="RH Sensor Temp")
    reference_pressure: List[Reading] = pydantic.Field(..., alias="Reference Pressure")
    saturation_extract_ec: List[Reading] = pydantic.Field(..., alias="Saturation Extract EC")
    soil_temperature: List[Reading] = pydantic.Field(..., alias="Soil Temperature")
    solar_radiation: List[Reading] = pydantic.Field(..., alias="Solar Radiation")
    vpd: List[Reading] = pydantic.Field(..., alias="VPD")
    vapor_pressure: List[Reading] = pydantic.Field(..., alias="Vapor Pressure")
    water_content: List[Reading] = pydantic.Field(..., alias="Water Content")
    wind_direction: List[Reading] = pydantic.Field(..., alias="Wind Direction")
    wind_speed: List[Reading] = pydantic.Field(..., alias="Wind Speed")
    x_axis_level: List[Reading] = pydantic.Field(..., alias="X-axis Level")
    y_axis_level: List[Reading] = pydantic.Field(..., alias="Y-axis Level")


class TahmoWeatherResponse(pydantic.BaseModel):
    pagination: PaginationData
    readings: TahmoWeatherData


class PullObservationsBadConfigException(Exception):
    def __init__(self, message: str, status_code=422):
        self.status_code = status_code
        self.message = message
        super().__init__(f'{self.status_code}: {self.message}')


class TahmoWeatherUnauthorizedException(Exception):
    def __init__(self, message: str, status_code=401):
        self.status_code = status_code
        self.message = message
        super().__init__(f'{self.status_code}: {self.message}')


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


async def get_readings_endpoint_response(integration, auth_config, config):
    readings_per_device = {}
    try:
        url = integration.base_url

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
                    headers={
                        'Authorization': 'Token {token}'.format(
                            token=auth_config.token
                        )
                    }
                )
                response.raise_for_status()

            response = response.json()

            readings = TahmoWeatherResponse.parse_obj({
                "pagination": response.get("pagination"),
                "readings": response.get("data")
            })

            readings_per_device[device] = readings

    except pydantic.ValidationError as ve:
        message = f'Error while parsing TAHMO Weather READINGS endpoint. {ve.json()}'
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
