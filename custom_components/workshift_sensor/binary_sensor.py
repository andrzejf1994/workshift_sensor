from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import Callable, Optional
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the 'active shift' binary sensor."""
    data = hass.data[DOMAIN][entry.entry_id]
    name_prefix = data.get("name", "Workshift")
    entity = WorkshiftActiveSensor(hass, entry, name_prefix)
    async_add_entities([entity], update_before_add=True)

class WorkshiftActiveSensor(BinarySensorEntity):
    """Binary sensor indicating if a work shift is currently in progress."""
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry, name_prefix: str):
        self.hass = hass
        self._entry = entry
        self._config = hass.data[DOMAIN][entry.entry_id]
        self._attr_name = f"{name_prefix} Active"
        self._attr_unique_id = f"{entry.entry_id}_active"
        # Parse config values
        self._shift_duration = int(self._config.get("shift_duration", 8))
        self._num_shifts = int(self._config.get("num_shifts", 1))
        self._start_times = [
            datetime.strptime(t, "%H:%M").time()
            for t in self._config.get("start_times", [])
        ]
        self._pattern = str(self._config.get("schedule", ""))
        try:
            self._base_date = datetime.strptime(self._config.get("schedule_start"), "%Y-%m-%d").date()
        except Exception:
            self._base_date = date.today()
        self._workday_entity = self._config.get("workday_sensor")
        self._use_workday_sensor = self._config.get("use_workday_sensor", True)
        # Timer for scheduled state changes
        self._timer_cancel: Optional[Callable[[], None]] = None
        self._attr_is_on = False  # initial state

    async def async_added_to_hass(self):
        """When added, determine initial state and set up timers."""
        now = dt_util.now()
        self._attr_is_on = self._is_shift_active(now)
        self._schedule_next_event(now)
        # Write initial state
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Cancel any scheduled timers on removal."""
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None

    def _get_schedule_code(self, day: date) -> int:
        """Get the shift code for a given date (considering workday sensor for that date)."""
        if not self._pattern:
            return 0
        days_diff = (day - self._base_date).days
        if days_diff < 0:
            return 0
        idx = days_diff % len(self._pattern)
        try:
            code = int(self._pattern[idx])
        except (ValueError, IndexError):
            _LOGGER.warning("Invalid schedule digit for day %s in pattern %s", day, self._pattern)
            return 0
        # Override as off if workday sensor indicates a non-workday and use_workday_sensor is enabled
        if self._use_workday_sensor and self._workday_entity:
            if day == date.today():
                state = self.hass.states.get(self._workday_entity)
                if state and state.state.lower() == "off":
                    return 0
        return code

    def _start_datetime(self, day: date, index: int):
        if index < len(self._start_times):
            start_time = self._start_times[index]
        else:
            _LOGGER.warning(
                "Start time for shift %s missing, defaulting to 00:00", index + 1
            )
            start_time = datetime.strptime("00:00", "%H:%M").time()
        start_of_day = dt_util.start_of_local_day(day)
        return start_of_day + timedelta(
            hours=start_time.hour,
            minutes=start_time.minute,
            seconds=start_time.second,
        )

    def _is_shift_active(self, reference: datetime) -> bool:
        """Check if currently within any active shift interval."""
        reference = dt_util.as_local(reference)
        today = reference.date()
        code_today = self._get_schedule_code(today)
        if code_today != 0:
            idx = code_today - 1
            start_dt = self._start_datetime(today, idx)
            end_dt = start_dt + timedelta(hours=self._shift_duration)
            if start_dt <= reference < end_dt:
                return True
        # If not, check if a shift from yesterday overlaps into now
        yesterday = today - timedelta(days=1)
        code_yest = self._get_schedule_code(yesterday)
        if code_yest != 0:
            idx = code_yest - 1
            y_start_dt = self._start_datetime(yesterday, idx)
            y_end_dt = y_start_dt + timedelta(hours=self._shift_duration)
            if y_end_dt.date() == today and reference < y_end_dt:
                return True
        return False

    def _schedule_next_event(self, now: datetime | None = None) -> None:
        """Schedule the next on/off state transition."""
        # Cancel any existing timer
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None
        if now is None:
            now = dt_util.now()
        now = dt_util.as_local(now)
        today = now.date()
        target_time = None
        if self._attr_is_on:
            # Currently in a shift: schedule when it ends
            code_today = self._get_schedule_code(today)
            if code_today != 0:
                idx = code_today - 1
                start_dt = self._start_datetime(today, idx)
                end_dt = start_dt + timedelta(hours=self._shift_duration)
                if now < end_dt:
                    target_time = end_dt
            if target_time is None:
                # Check if it is an overnight shift from yesterday
                yesterday = today - timedelta(days=1)
                code_yest = self._get_schedule_code(yesterday)
                if code_yest != 0:
                    idx = code_yest - 1
                    y_start_dt = self._start_datetime(yesterday, idx)
                    y_end_dt = y_start_dt + timedelta(hours=self._shift_duration)
                    if now < y_end_dt:
                        target_time = y_end_dt
            if target_time:
                _LOGGER.debug("Scheduling shift end at %s", target_time)
                self._timer_cancel = async_track_point_in_time(
                    self.hass, self._timer_trigger, dt_util.as_utc(target_time)
                )
        else:
            # Currently off: schedule next shift start
            code_today = self._get_schedule_code(today)
            if code_today != 0:
                idx = code_today - 1
                start_dt = self._start_datetime(today, idx)
                if now < start_dt:
                    target_time = start_dt
            if target_time is None:
                # Find first future day with a shift
                for d in range(1, len(self._pattern) + 1):
                    future_date = today + timedelta(days=d)
                    code_future = self._get_schedule_code(future_date)
                    if code_future != 0:
                        idx = code_future - 1
                        start_dt = self._start_datetime(future_date, idx)
                        if start_dt > now:
                            target_time = start_dt
                            break
            if target_time:
                _LOGGER.debug("Scheduling shift start at %s", target_time)
                self._timer_cancel = async_track_point_in_time(
                    self.hass, self._timer_trigger, dt_util.as_utc(target_time)
                )

    @callback
    def _timer_trigger(self, _now: datetime):
        """Handle a scheduled state change event."""
        # Update the current state
        reference = dt_util.now()
        self._attr_is_on = self._is_shift_active(reference)
        self.async_write_ha_state()
        # Schedule the next transition
        self._schedule_next_event(reference)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        name = self._config.get("name") or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )
