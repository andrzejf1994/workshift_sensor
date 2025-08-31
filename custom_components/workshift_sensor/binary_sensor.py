from __future__ import annotations
from datetime import datetime, timedelta, date
from typing import Optional
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.event import async_track_point_in_time

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
        self._attr_unique_id = f"{name_prefix.lower()}_active"
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
        # Timer for scheduled state changes
        self._timer_cancel: Optional[callback] = None
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
        if not self._pattern:
            return 0
        days_diff = (day - self._base_date).days
        if days_diff < 0:
            return 0
        idx = days_diff % len(self._pattern) if self._pattern else 0
        code = int(self._pattern[idx]) if idx < len(self._pattern) else 0
        # Override as off if workday sensor indicates a non-workday and use_workday_sensor is enabled
        if self._use_workday_sensor and self._workday_entity:
            if day == date.today():
                state = self.hass.states.get(self._workday_entity)
                if state and state.state.lower() == "off":
                    return 0
        return code

    def _is_shift_active_now(self) -> bool:
        """Check if currently within any active shift interval."""
        now = datetime.now()
        today = now.date()
        code_today = self._get_schedule_code(today)
        if code_today != 0:
            idx = code_today - 1
            start_time = self._start_times[idx] if idx < len(self._start_times) else datetime.strptime("00:00", "%H:%M").time()
            start_dt = datetime.combine(today, start_time)
            end_dt = start_dt + timedelta(hours=self._shift_duration)
            if start_dt <= now < end_dt:
                # Currently within today's shift interval
                return True
        # If not, check if a shift from yesterday overlaps into now
        yesterday = today - timedelta(days=1)
        code_yest = self._get_schedule_code(yesterday)
        if code_yest != 0:
            idx = code_yest - 1
            y_start_time = self._start_times[idx] if idx < len(self._start_times) else datetime.strptime("00:00", "%H:%M").time()
            y_start_dt = datetime.combine(yesterday, y_start_time)
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
        now = datetime.now()
        today = now.date()
        target_time = None
        if self._attr_is_on:
            # Currently in a shift: schedule when it ends
            code_today = self._get_schedule_code(today)
            if code_today != 0:
                idx = code_today - 1
                start_dt = datetime.combine(today, self._start_times[idx] if idx < len(self._start_times) else datetime.strptime("00:00","%H:%M").time())
                end_dt = start_dt + timedelta(hours=self._shift_duration)
                if now < end_dt:
                    target_time = end_dt
            if target_time is None:
                # Check if it is an overnight shift from yesterday
                yesterday = today - timedelta(days=1)
                code_yest = self._get_schedule_code(yesterday)
                if code_yest != 0:
                    idx = code_yest - 1
                    y_start_dt = datetime.combine(yesterday, self._start_times[idx] if idx < len(self._start_times) else datetime.strptime("00:00","%H:%M").time())
                    y_end_dt = y_start_dt + timedelta(hours=self._shift_duration)
                    if now < y_end_dt:
                        target_time = y_end_dt
            if target_time:
                _LOGGER.debug("Scheduling shift end at %s", target_time)
                self._timer_cancel = async_track_point_in_time(self.hass, self._timer_trigger, target_time)
        else:
            # Currently off: schedule next shift start
            code_today = self._get_schedule_code(today)
            if code_today != 0:
                idx = code_today - 1
                start_dt = datetime.combine(today, self._start_times[idx] if idx < len(self._start_times) else datetime.strptime("00:00","%H:%M").time())
                if now < start_dt:
                    target_time = start_dt
            if target_time is None:
                # Find first future day with a shift
                for d in range(1, len(self._pattern) + 1):
                    future_date = today + timedelta(days=d)
                    code_future = self._get_schedule_code(future_date)
                    if code_future != 0:
                        idx = code_future - 1
                        start_dt = datetime.combine(future_date, self._start_times[idx] if idx < len(self._start_times) else datetime.strptime("00:00","%H:%M").time())
                        if start_dt > now:
                            target_time = start_dt
                            break
            if target_time:
                _LOGGER.debug("Scheduling shift start at %s", target_time)
                self._timer_cancel = async_track_point_in_time(self.hass, self._timer_trigger, target_time)

    @callback
    def _timer_trigger(self, _now: datetime):
        """Handle a scheduled state change event."""
        # Update the current state
        self._attr_is_on = self._is_shift_active_now()
        self.async_write_ha_state()
        # Schedule the next transition
        self._schedule_next_event()
