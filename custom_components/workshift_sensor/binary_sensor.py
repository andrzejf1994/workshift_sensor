from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import DEFAULT_TIME_ZONE

from . import DOMAIN
from .schedule import WorkshiftSchedule

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up the 'active shift' binary sensor."""
    data = hass.data[DOMAIN][entry.entry_id]
    base_name = data.get("name", "Workshift")
    name_prefix = data.get("name_prefix") or base_name
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
        self._schedule = WorkshiftSchedule(hass, self._config)
        self._tz = self._schedule.tz
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

    def _is_shift_active_now(self) -> bool:
        """Check if currently within any active shift interval."""
        now = dt_util.now(self._tz)
        return self._schedule.shift_covering(now) is not None

    def _schedule_next_event(self):
        """Schedule the next on/off state transition."""
        # Cancel any existing timer
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None
        now = dt_util.now(self._tz)
        target_time = None
        if self._attr_is_on:
            active_shift = self._schedule.shift_covering(now)
            if active_shift:
                target_time = active_shift.end
            if target_time:
                _LOGGER.debug("Scheduling shift end at %s", target_time)
                self._timer_cancel = async_track_point_in_utc_time(self.hass, self._timer_trigger, dt_util.as_utc(target_time))
        else:
            # Currently off: schedule next shift start
            next_shift = self._schedule.next_shift_after(now)
            if next_shift:
                target_time = next_shift.start
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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        name = self._config.get("name") or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )
