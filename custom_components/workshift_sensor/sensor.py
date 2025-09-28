from __future__ import annotations
from datetime import datetime, timedelta, date, time as time_
from typing import Any
import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    name = data.get("name", "Workshift")
    async_add_entities([
        WorkshiftDaySensor(hass, entry, name, 0),
        WorkshiftDaySensor(hass, entry, name, 1),
    ], update_before_add=True)


class WorkshiftDaySensor(SensorEntity):
    """Sensor pokazujący numer zmiany dla dzisiaj lub jutra, z uwzględnieniem dni wolnych."""
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
        name: str,
        offset: int,
    ):
        self.hass = hass
        self._entry = entry
        self._config = hass.data[DOMAIN][entry.entry_id]
        self._offset = offset
        suffix = "today" if offset == 0 else "tomorrow"
        self._attr_name = f"{name} {suffix.title()}"
        self._attr_unique_id = f"{entry.entry_id}_day_{suffix}"
        self._attr_extra_state_attributes: dict[str, Any] = {}

        # Parametry zmian
        self.shift_duration = int(self._config.get("shift_duration", 8))
        self.num_shifts = int(self._config.get("num_shifts", 1))
        self.start_times = [
            datetime.strptime(t, "%H:%M").time() for t in self._config.get("start_times", [])
        ]
        # Harmonogram jako ciąg cyfr
        self._pattern = str(self._config.get("schedule", ""))
        try:
            self._base_date = datetime.strptime(
                self._config.get("schedule_start"), "%Y-%m-%d"
            ).date()
        except Exception:
            self._base_date = date.today()

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

    async def async_added_to_hass(self):
        """Odświeżenie o północy + nasłuchiwanie zmian workday_sensor i workday_sensor_tomorrow."""
        # Inicjalne odświeżenie
        self._update_state()
        self.async_write_ha_state()

        # 1) Harmonogram o północy
        now = datetime.now()
        next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        @callback
        def midnight_cb(ts: datetime):
            self._update_state()
            self.async_write_ha_state()
            async_track_point_in_time(self.hass, midnight_cb, ts + timedelta(days=1))

        async_track_point_in_time(self.hass, midnight_cb, next_midnight)

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
                lambda event: (self._update_state(), self.async_write_ha_state()),
            )

    def _get_schedule_code(self, day: date) -> int:
        """Zwraca kod zmiany dla danego dnia, z uwzględnieniem dni wolnych jeśli włączone."""
        if not self._pattern:
            return 0
        diff = (day - self._base_date).days
        if diff < 0:
            return 0
        code = int(self._pattern[diff % len(self._pattern)])
        
        # Sprawdź workday sensor tylko jeśli opcja jest włączona
        if self._use_workday_sensor:
            # Dobór encji workday na podstawie dnia
            if day == date.today():
                entity_id = self._workday_today
            elif day == date.today() + timedelta(days=1):
                entity_id = self._workday_tomorrow
            else:
                entity_id = None
            # Override na 'off' jeśli workday sensor wskazuje dzień wolny
            if entity_id:
                state = self.hass.states.get(entity_id)
                if state and state.state.lower() == "off":
                    return 0
        return code

    def _update_state(self):
        """Ustawia wartość sensora i atrybuty startu/końca zmiany."""
        target = date.today() + timedelta(days=self._offset)
        code = self._get_schedule_code(target)
        if code == 0:
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {"shift_start": None, "shift_end": None}
        else:
            self._attr_native_value = code
            idx = code - 1
            start_dt = datetime.combine(target, self.start_times[idx])
            end_dt = start_dt + timedelta(hours=self.shift_duration)
            self._attr_extra_state_attributes = {
                "shift_start": start_dt.isoformat(),
                "shift_end": end_dt.isoformat(),
            }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        name = self._config.get("name") or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )