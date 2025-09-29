"""Constants for the Workshift Sensor integration."""
from __future__ import annotations

from typing import Final

DOMAIN: Final = "workshift_sensor"

PLATFORMS: Final = ["sensor", "binary_sensor"]

CONF_WORKDAY_SENSOR: Final = "workday_sensor"
CONF_WORKDAY_SENSOR_TOMORROW: Final = "workday_sensor_tomorrow"
CONF_USE_WORKDAY_SENSOR: Final = "use_workday_sensor"
CONF_SHIFT_DURATION: Final = "shift_duration"
CONF_NUM_SHIFTS: Final = "num_shifts"
CONF_START_TIMES: Final = "start_times"
CONF_SCHEDULE_START: Final = "schedule_start"
CONF_SCHEDULE: Final = "schedule"

DEFAULT_NAME: Final = ""
DEFAULT_SHIFT_DURATION: Final = 8
DEFAULT_NUM_SHIFTS: Final = 3
DEFAULT_WORKDAY_SENSOR: Final = "binary_sensor.workday_sensor"
MAX_SHIFTS: Final = 9
