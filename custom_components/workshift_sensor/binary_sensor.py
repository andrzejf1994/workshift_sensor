from __future__ import annotations
from datetime import datetime, timedelta, date
from typing import Callable, Optional
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import DEFAULT_TIME_ZONE

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
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
        self._start_times = [datetime.strptime(t, "%H:%M").time() for t in self._config.get("start_times", [])]
        self._pattern = str(self._config.get("schedule", ""))
        try:
            self._base_date = datetime.strptime(self._config.get("schedule_start"), "%Y-%m-%d").date()
        except Exception:
            self._base_date = date.today()
        self._workday_entity = self._config.get("workday_sensor")
        self._use_workday_sensor = self._config.get("use_workday_sensor", True)
        tz = dt_util.get_time_zone(self.hass.config.time_zone)
        self._tz = tz or DEFAULT_TIME_ZONE
        self._manual_days_off = self._parse_manual_days_off(self._config.get("manual_days_off", []))
        # Timer for scheduled state changes
        self._timer_cancel: Optional[Callable[[], None]] = None
        self._attr_is_on = False  # initial state

    async def async_added_to_hass(self):
        """When added, determine initial state and set up timers."""
        # Set initial state
        self._attr_is_on = self._is_shift_active_now()
        # Schedule the next state change
        self._schedule_next_event()
        # Write initial state
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        """Cancel any scheduled timers on removal."""
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None

    def _get_schedule_code(self, day: date) -> int:
        """Get the shift code for a given date (considering workday sensor for that date)."""
        if self._is_manual_day_off(day):
            return 0
        if not self._pattern:
            return 0
        days_diff = (day - self._base_date).days
        if days_diff < 0:
            return 0
        try:
            idx = days_diff % len(self._pattern)
            code = int(self._pattern[idx])
        except (ValueError, IndexError):
            _LOGGER.warning("Invalid schedule pattern value for %s", day)
            return 0
        # Override as off if workday sensor indicates a non-workday and use_workday_sensor is enabled
        if self._use_workday_sensor and self._workday_entity:
            if day == dt_util.now(self._tz).date():
                state = self.hass.states.get(self._workday_entity)
                if state and state.state.lower() == "off":
                    return 0
        return code

    def _parse_manual_days_off(self, entries: list[dict]) -> list[tuple[date, date]]:
        """Normalize manual days off to date ranges."""
        ranges: list[tuple[date, date]] = []
        for entry in entries:
            start = entry.get("start")
            end = entry.get("end", start)
            try:
                start_date = datetime.strptime(start, "%Y-%m-%d").date()
                end_date = datetime.strptime(end, "%Y-%m-%d").date()
            except Exception:
                _LOGGER.warning("Invalid manual day off entry skipped: %s", entry)
                continue
            if end_date < start_date:
                start_date, end_date = end_date, start_date
            ranges.append((start_date, end_date))
        return ranges

    def _is_manual_day_off(self, day: date) -> bool:
        """Check if date is marked as a manual day off."""
        return any(start <= day <= end for start, end in self._manual_days_off)

    def _is_shift_active_now(self) -> bool:
        """Check if currently within any active shift interval."""
        now = dt_util.now(self._tz)
        today = now.date()
        code_today = self._get_schedule_code(today)
        if code_today != 0:
            idx = code_today - 1
            start_time = self._get_start_time(idx)
            if start_time:
                start_dt = dt_util.get_default_time_zone().localize(datetime.combine(today, start_time))
                end_dt = start_dt + timedelta(hours=self._shift_duration)
                if start_dt <= now < end_dt:
                    # Currently within today's shift interval
                    return True
        # If not, check if a shift from yesterday overlaps into now
        yesterday = today - timedelta(days=1)
        code_yest = self._get_schedule_code(yesterday)
        if code_yest != 0:
            idx = code_yest - 1
            y_start_time = self._get_start_time(idx)
            if y_start_time:
                y_start_dt = dt_util.get_default_time_zone().localize(datetime.combine(yesterday, y_start_time))
                y_end_dt = y_start_dt + timedelta(hours=self._shift_duration)
                if y_end_dt.date() == today and now < y_end_dt:
                    # Yesterday's shift continues into today
                    return True
        return False

    def _schedule_next_event(self):
        """Schedule the next on/off state transition."""
        # Cancel any existing timer
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None
        now = dt_util.now(self._tz)
        today = now.date()
        target_time = None
        if self._attr_is_on:
            # Currently in a shift: schedule when it ends
            code_today = self._get_schedule_code(today)
            if code_today != 0:
                idx = code_today - 1
                start_time = self._get_start_time(idx)
                if start_time:
                    start_dt = dt_util.get_default_time_zone().localize(datetime.combine(today, start_time))
                    end_dt = start_dt + timedelta(hours=self._shift_duration)
                    if now < end_dt:
                        target_time = end_dt
            if target_time is None:
                # Check if it is an overnight shift from yesterday
                yesterday = today - timedelta(days=1)
                code_yest = self._get_schedule_code(yesterday)
                if code_yest != 0:
                    idx = code_yest - 1
                    y_start_time = self._get_start_time(idx)
                    if y_start_time:
                        y_start_dt = dt_util.get_default_time_zone().localize(datetime.combine(yesterday, y_start_time))
                        y_end_dt = y_start_dt + timedelta(hours=self._shift_duration)
                        if now < y_end_dt:
                            target_time = y_end_dt
            if target_time:
                _LOGGER.debug("Scheduling shift end at %s", target_time)
                self._timer_cancel = async_track_point_in_utc_time(self.hass, self._timer_trigger, dt_util.as_utc(target_time))
        else:
            # Currently off: schedule next shift start
            code_today = self._get_schedule_code(today)
            if code_today != 0:
                idx = code_today - 1
                start_time = self._get_start_time(idx)
                if start_time:
                    start_dt = dt_util.get_default_time_zone().localize(datetime.combine(today, start_time))
                    if now < start_dt:
                        target_time = start_dt
            if target_time is None:
                # Find first future day with a shift
                for d in range(1, len(self._pattern) + 1):
                    future_date = today + timedelta(days=d)
                    code_future = self._get_schedule_code(future_date)
                    if code_future != 0:
                        idx = code_future - 1
                        start_time = self._get_start_time(idx)
                        if start_time:
                            start_dt = dt_util.get_default_time_zone().localize(datetime.combine(future_date, start_time))
                            if start_dt > now:
                                target_time = start_dt
                                break
            if target_time:
                _LOGGER.debug("Scheduling shift start at %s", target_time)
                self._timer_cancel = async_track_point_in_utc_time(self.hass, self._timer_trigger, dt_util.as_utc(target_time))

    @callback
    def _timer_trigger(self, _now: datetime):
        """Handle a scheduled state change event."""
        # Update the current state
        self._attr_is_on = self._is_shift_active_now()
        self.async_write_ha_state()
        # Schedule the next transition
        self._schedule_next_event()

    def _get_start_time(self, idx: int):
        """Return start time for given index with validation."""
        if idx < 0 or idx >= len(self._start_times):
            _LOGGER.warning("Shift index %s out of range for configured start times", idx + 1)
            return None
        return self._start_times[idx]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        name = self._config.get("name") or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )
