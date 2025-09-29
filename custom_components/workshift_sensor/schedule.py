"""Scheduling helpers for the Workshift Sensor integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import logging
from typing import Tuple

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .util import WorkshiftConfigData

_LOGGER = logging.getLogger(__name__)


@dataclass
class WorkshiftSchedule:
    """Encapsulates schedule computations for a workshift configuration."""

    config: WorkshiftConfigData
    _start_times: Tuple[time, ...] = field(init=False)
    _base_date: date = field(init=False)

    def __post_init__(self) -> None:
        self._start_times = self.config.start_times_as_time
        self._base_date = self._resolve_base_date()

    def _resolve_base_date(self) -> date:
        base = self.config.schedule_start_date
        if base is None:
            base = dt_util.now().date()
        return base

    def _workday_entity(self, target: date, today: date | None = None) -> str | None:
        if not self.config.use_workday_sensor:
            return None
        if today is None:
            today = dt_util.now().date()
        if target == today:
            return self.config.workday_sensor
        if target == today + timedelta(days=1):
            return self.config.workday_sensor_tomorrow or self.config.workday_sensor
        return None

    def shift_code(
        self, hass: HomeAssistant, target: date, *, today: date | None = None
    ) -> int:
        pattern = self.config.schedule
        if not pattern:
            return 0
        days_diff = (target - self._base_date).days
        if days_diff < 0:
            return 0
        try:
            code = int(pattern[days_diff % len(pattern)])
        except (ValueError, IndexError):
            _LOGGER.warning(
                "Invalid schedule entry at index %s for day %s", days_diff, target
            )
            return 0
        if code <= 0:
            return 0
        entity_id = self._workday_entity(target, today=today)
        if entity_id:
            state = hass.states.get(entity_id)
            if state and state.state.lower() == "off":
                return 0
        return code

    def start_datetime(self, day: date, shift_index: int) -> datetime:
        if 0 <= shift_index < len(self._start_times):
            start_time = self._start_times[shift_index]
        else:
            _LOGGER.warning(
                "Missing start time for shift %s, defaulting to 00:00", shift_index + 1
            )
            start_time = time()
        start_of_day = dt_util.start_of_local_day(day)
        return start_of_day + timedelta(
            hours=start_time.hour,
            minutes=start_time.minute,
            seconds=start_time.second,
        )

    def duration(self) -> timedelta:
        return timedelta(hours=self.config.shift_duration)

    @property
    def pattern_length(self) -> int:
        return self.config.pattern_length
