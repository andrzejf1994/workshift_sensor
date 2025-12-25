from __future__ import annotations
from datetime import datetime, timedelta, date
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

        tz = dt_util.get_time_zone(self.hass.config.time_zone)
        self._tz = tz or DEFAULT_TIME_ZONE
        self._manual_days_off = self._parse_manual_days_off(self._config.get("manual_days_off", []))

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

    def _get_schedule_code(self, day: date) -> int:
        """Zwraca kod zmiany dla danego dnia, z uwzględnieniem dni wolnych jeśli włączone."""
        if self._is_manual_day_off(day):
            return 0
        if not self._pattern:
            return 0
        diff = (day - self._base_date).days
        if diff < 0:
            return 0
        try:
            code = int(self._pattern[diff % len(self._pattern)])
        except (ValueError, IndexError):
            _LOGGER.warning("Invalid schedule pattern value for %s", day)
            return 0
        
        # Sprawdź workday sensor tylko jeśli opcja jest włączona
        if self._use_workday_sensor:
            # Dobór encji workday na podstawie dnia
            today = dt_util.now(self._tz).date()
            if day == today:
                entity_id = self._workday_today
            elif day == today + timedelta(days=1):
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
        today = dt_util.now(self._tz).date()
        target = today + timedelta(days=self._offset)
        code = self._get_schedule_code(target)
        if code == 0:
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {"shift_start": None, "shift_end": None}
            return

        idx = code - 1
        start_time = self.start_times[idx] if idx < len(self.start_times) else None
        if start_time is None:
            _LOGGER.warning(
                "Shift code %s has no matching start time configured", code
            )
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {"shift_start": None, "shift_end": None}
            return

        self._attr_native_value = code
        target_start = dt_util.get_default_time_zone().localize(
            datetime.combine(target, start_time)
        )
        end_dt = target_start + timedelta(hours=self.shift_duration)
        self._attr_extra_state_attributes = {
            "shift_start": target_start.isoformat(),
            "shift_end": end_dt.isoformat(),
        }

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
        return any(start <= day <= end for start, end in self._manual_days_off)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        name = self._config.get("name") or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )
