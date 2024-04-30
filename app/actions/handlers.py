import datetime
import httpx
import logging
import stamina

import app.actions.client as client
import app.services.gundi as gundi_tools

from app.actions.configurations import PullObservationsConfig
from app.services.activity_logger import activity_logger
from app.services.state import IntegrationStateManager


logger = logging.getLogger(__name__)


state_manager = IntegrationStateManager()


async def filter_and_transform(device, readings, integration_id, action_id):
    def transform():
        current_log = 0
        total_logs = readings.pagination.page_num_readings

        transformed_data = []

        while current_log < total_logs:
            readings_dict = {}
            for reading in readings.readings:
                reading_type = reading[0]
                reading_dict = reading[1][0].readings[current_log].dict()

                reading_datetime = datetime.datetime.strptime(
                    reading_dict.pop("reading_datetime"),
                    "%Y-%m-%d %H:%M:%S%z"
                )

                readings_dict.update(
                    {
                        f'{reading_type}_{log_key}': log_value
                        for log_key, log_value in reading_dict.items()
                        if log_value is not None
                    }
                )

            transformed_data.append(
                {
                    "source": device,
                    "source_name": device,
                    'type': "stationary-object",
                    "subtype": "weather_station",
                    "recorded_at": reading_datetime,
                    "location": {"lat": 0.0, "lon": 0.0},  # Just to avoid 400 after posting to ER
                    "additional": readings_dict
                }
            )

            current_log += 1

        return transformed_data

    # Get current state for the device
    current_state = await state_manager.get_state(
        integration_id,
        action_id,
        device
    )

    if current_state:
        # Compare current state with new data
        latest_device_timestamp = datetime.datetime.strptime(
            current_state.get("latest_device_timestamp"),
            '%Y-%m-%d %H:%M:%S%z'
        )

        if readings.pagination.page_start_date < latest_device_timestamp:
            # Data is not new, not transform
            logger.info(
                f"Excluding device ID '{device}' readings from '{readings.pagination.page_start_date}'"
            )
            return []

    return transform()


@activity_logger()
async def action_pull_observations(integration, action_config: PullObservationsConfig):
    logger.info(f"Executing pull_observations action with integration {integration} and action_config {action_config}...")
    try:
        response_per_device = []
        async for attempt in stamina.retry_context(
                on=httpx.HTTPError,
                attempts=3,
                wait_initial=datetime.timedelta(seconds=60),
                wait_max=datetime.timedelta(seconds=60),
        ):
            with attempt:
                readings = await client.get_readings_endpoint_response(
                    integration=integration,
                    auth_config=client.get_auth_config(integration),
                    config=client.get_pull_observations_config(integration)
                )

        if readings:
            logger.info(f"Readings pulled with success.")

            for device, device_readings in readings.items():
                transformed_data = await filter_and_transform(
                    device,
                    device_readings,
                    str(integration.id),
                    "pull_observations"
                )

                if transformed_data:
                    # Send transformed data to Sensors API V2
                    async for attempt in stamina.retry_context(
                            on=httpx.HTTPError,
                            attempts=3,
                            wait_initial=datetime.timedelta(seconds=10),
                            wait_max=datetime.timedelta(seconds=10),
                    ):
                        with attempt:
                            try:
                                response = await gundi_tools.send_observations_to_gundi(
                                    observations=transformed_data,
                                    integration_id=integration.id
                                )
                            except httpx.HTTPError as e:
                                msg = f'Sensors API returned error for integration_id: {str(integration.id)}. Exception: {e}'
                                logger.exception(
                                    msg,
                                    extra={
                                        'needs_attention': True,
                                        'integration_id': str(integration.id),
                                        'action_id': "pull_observations"
                                    }
                                )
                                response_per_device.append({"device": device, "response": [msg]})
                            else:
                                # Update state
                                state = {
                                    "latest_device_timestamp": device_readings.pagination.page_end_date
                                }
                                await state_manager.set_state(
                                    str(integration.id),
                                    "pull_observations",
                                    state,
                                    device,
                                )
                                response_per_device.append({"device": device, "response": response})
                else:
                    response_per_device.append({"device": device, "response": []})
        else:
            msg = f'No observations extracted for integration_id: {str(integration.id)}.'
            logger.warning(msg)
            response_per_device.append({"msg": msg})
    except httpx.HTTPError as e:
        message = f"pull_observations action returned error."
        logger.exception(message, extra={
            "integration_id": str(integration.id),
            "attention_needed": True
        })
        raise e
    else:
        return response_per_device
