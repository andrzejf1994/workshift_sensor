from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any, Callable, Optional
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from . import DOMAIN
from .schedule import WorkshiftSchedule

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up the workshift day sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    base_name = data.get("name", "Workshift")
    name_prefix = data.get("name_prefix") or base_name
    
    entities = [
        WorkshiftDaySensor(hass, entry, base_name, name_prefix, 0),
        WorkshiftDaySensor(hass, entry, base_name, name_prefix, 1),
    ]
    
    async_add_entities(entities, update_before_add=True)


class WorkshiftDaySensor(SensorEntity):
    """Sensor pokazujący numer zmiany dla dzisiaj lub jutra, z uwzględnieniem dni wolnych."""
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
        base_name: str,
        name_prefix: str,
        offset: int,
    ):
        self.hass = hass
        self._entry = entry
        self._config = hass.data[DOMAIN][entry.entry_id]
        self._offset = offset
        suffix = "today" if offset == 0 else "tomorrow"
        self._attr_name = f"{name_prefix} {suffix.title()}"
        self._attr_unique_id = f"{entry.entry_id}_day_{suffix}"
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._schedule = WorkshiftSchedule(hass, self._config)
        self._device_name = base_name

        # FIX #2: Timer cancellation handlers
        self._midnight_cancel: Optional[Callable[[], None]] = None
        self._workday_cancel: Optional[Callable[[], None]] = None

        self._use_workday_sensor = self._config.get("use_workday_sensor", True)
        if self._use_workday_sensor:
            if offset == 0:
                self._workday_today = self._config.get("workday_sensor")
                self._workday_tomorrow = self._config.get("workday_sensor_tomorrow") or self._workday_today
            else:
                self._workday_today = self._config.get("workday_sensor")
                self._workday_tomorrow = self._config.get("workday_sensor_tomorrow") or self._workday_today
        else:
            self._workday_today = None
            self._workday_tomorrow = None

    async def async_added_to_hass(self):
        """Odświeżenie o północy + nasłuchiwanie zmian workday_sensor."""
        self._update_state()
        self.async_write_ha_state()

        self._schedule_midnight_update()

        entities: list[str] = []
        if self._use_workday_sensor:
            if self._workday_today:
                entities.append(self._workday_today)
            if self._workday_tomorrow and self._workday_tomorrow != self._workday_today:
                entities.append(self._workday_tomorrow)

        if entities:
            self._workday_cancel = async_track_state_change_event(
                self.hass,
                entities,
                self._handle_workday_state_change,
            )

    async def async_will_remove_from_hass(self):
        """FIX #2: Cancel all timers on removal."""
        if self._midnight_cancel:
            self._midnight_cancel()
            self._midnight_cancel = None
        if self._workday_cancel:
            self._workday_cancel()
            self._workday_cancel = None

    def _schedule_midnight_update(self):
        """Schedule the next midnight update."""
        if self._midnight_cancel:
            self._midnight_cancel()
        
        now = dt_util.now(self._schedule.tz)
        next_midnight = dt_util.start_of_local_day(now) + timedelta(days=1)

        @callback
        def midnight_cb(ts: datetime):
            self._update_state()
            self.async_write_ha_state()
            self._schedule_midnight_update()

        self._midnight_cancel = async_track_point_in_utc_time(
            self.hass, 
            midnight_cb, 
            dt_util.as_utc(next_midnight)
        )

    @callback
    def _handle_workday_state_change(self, _event) -> None:
        """React to workday sensor updates."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self):
        """Ustawia wartość sensora i atrybuty startu/końca zmiany."""
        today = dt_util.now(self._schedule.tz).date()
        target = today + timedelta(days=self._offset)
        shift = self._schedule.get_shift(target)
        if shift is None:
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {
                "shift_start": None, 
                "shift_end": None
            }
            return

        self._attr_native_value = shift.code
        self._attr_extra_state_attributes = {
            "shift_start": shift.start.isoformat(),
            "shift_end": shift.end.isoformat(),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._device_name,
            manufacturer="Workshift Sensor",
        )
