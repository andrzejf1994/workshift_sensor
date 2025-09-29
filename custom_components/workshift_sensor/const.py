"""Constants for the Workshift Sensor integration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import List, Optional

DOMAIN = "workshift_sensor"
PLATFORMS = ["sensor", "binary_sensor"]

CONF_ENTRY_NAME = "entry_name"
CONF_USE_WORKDAY_SENSOR = "use_workday_sensor"
CONF_WORKDAY_ENTITY_TODAY = "workday_entity_today"
CONF_WORKDAY_ENTITY_TOMORROW = "workday_entity_tomorrow"
CONF_SHIFT_HOURS = "shift_hours"
CONF_SHIFTS_PER_DAY = "shifts_per_day"
CONF_SHIFT_STARTS = "shift_starts"
CONF_SCHEDULE_START_DATE = "schedule_start_date"
CONF_SCHEDULE_STRING = "schedule_string"

DEFAULT_SHIFT_HOURS = 8
DEFAULT_SHIFTS_PER_DAY = 3
DEFAULT_SCHEDULE_STRING = "333330022222001111100"

SENSOR_TODAY = "today_shift"
SENSOR_TOMORROW = "tomorrow_shift"
BINARY_SENSOR_ON_SHIFT = "on_shift"

DEVICE_MANUFACTURER = "Workshift Tools"


@dataclass(slots=True)
class WorkshiftConfigData:
    """Container for validated Workshift configuration."""

    entry_name: str
    use_workday_sensor: bool
    workday_entity_today: Optional[str]
    workday_entity_tomorrow: Optional[str]
    shift_hours: int
    shifts_per_day: int
    shift_starts: List[time]
    schedule_start_date: date
    schedule_string: str

    @property
    def workday_entities(self) -> List[str]:
        """Return available workday sensor entity IDs."""

        entities: List[str] = []
        if self.workday_entity_today:
            entities.append(self.workday_entity_today)
        if self.workday_entity_tomorrow and (
            self.workday_entity_tomorrow != self.workday_entity_today
        ):
            entities.append(self.workday_entity_tomorrow)
        return entities


@dataclass(slots=True)
class WorkshiftInfo:
    """Represents a resolved shift for a given day."""

    shift_index: int
    start: datetime
    end: datetime


class WorkshiftSchedule:
    """Provides utilities for resolving shifts based on a cyclic schedule."""

    def __init__(self, config: WorkshiftConfigData) -> None:
        self._config = config

    def _index_for_date(self, target_date: date) -> int:
        offset = (target_date - self._config.schedule_start_date).days
        length = len(self._config.schedule_string)
        # Handle negative offsets by wrapping around.
        return offset % length

    def get_shift_code(self, target_date: date) -> int:
        """Return the scheduled shift code for the given date."""

        index = self._index_for_date(target_date)
        return int(self._config.schedule_string[index])

    def get_shift_info(self, target_date: date) -> Optional[WorkshiftInfo]:
        """Return detailed shift info for the given date, if any."""

        shift_code = self.get_shift_code(target_date)
        if shift_code <= 0:
            return None
        if shift_code > self._config.shifts_per_day:
            return None

        start_time = self._config.shift_starts[shift_code - 1]
        start_dt = datetime.combine(target_date, start_time)
        end_dt = start_dt + timedelta(hours=self._config.shift_hours)
        return WorkshiftInfo(shift_index=shift_code, start=start_dt, end=end_dt)
