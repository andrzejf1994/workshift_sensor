from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import DEFAULT_TIME_ZONE

from . import DOMAIN
from .schedule import WorkshiftSchedule

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    base_name = data.get("name", "Workshift")
    name_prefix = data.get("name_prefix") or base_name
    async_add_entities([
        WorkshiftDaySensor(hass, entry, base_name, name_prefix, 0),
        WorkshiftDaySensor(hass, entry, base_name, name_prefix, 1),
    ], update_before_add=True)


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

        # Ustawienia dla workday sensor
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

        tz = dt_util.get_time_zone(self.hass.config.time_zone)
        self._tz = tz or DEFAULT_TIME_ZONE

    async def async_added_to_hass(self):
        """Odświeżenie o północy + nasłuchiwanie zmian workday_sensor i workday_sensor_tomorrow."""
        # Inicjalne odświeżenie
        self._update_state()
        self.async_write_ha_state()

        # 1) Harmonogram o północy
        now = dt_util.now(self._tz)
        next_midnight = dt_util.start_of_local_day(now) + timedelta(days=1)

        @callback
        def midnight_cb(ts: datetime):
            self._update_state()
            self.async_write_ha_state()
            async_track_point_in_utc_time(self.hass, midnight_cb, dt_util.as_utc(ts + timedelta(days=1)))

        async_track_point_in_utc_time(self.hass, midnight_cb, dt_util.as_utc(next_midnight))

        # 2) Nasłuchiwanie zmian encji workday dla dziś i jutra (jeśli włączone)
        entities: list[str] = []
        if self._use_workday_sensor:
            if self._workday_today:
                entities.append(self._workday_today)
            if self._workday_tomorrow and self._workday_tomorrow != self._workday_today:
                entities.append(self._workday_tomorrow)

        if entities:
            async_track_state_change_event(
                self.hass,
                entities,
                self._handle_workday_state_change,
            )

    @callback
    def _handle_workday_state_change(self, _event) -> None:
        """React to workday sensor updates."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self):
        """Ustawia wartość sensora i atrybuty startu/końca zmiany."""
        today = dt_util.now(self._tz).date()
        target = today + timedelta(days=self._offset)
        shift = self._schedule.get_shift(target)
        if shift is None:
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {"shift_start": None, "shift_end": None}
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
