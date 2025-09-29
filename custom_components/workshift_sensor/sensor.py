"""Sensor platform for Workshift Sensor integration."""
from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WorkshiftEntityMixin, WorkshiftRuntimeData
from .const import DOMAIN, SENSOR_TODAY, SENSOR_TOMORROW, WorkshiftInfo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Workshift sensors for a config entry."""

    runtime: WorkshiftRuntimeData = hass.data[DOMAIN][entry.entry_id]
    entities = [
        WorkshiftSensor(entry, runtime, SENSOR_TODAY),
        WorkshiftSensor(entry, runtime, SENSOR_TOMORROW),
    ]
    async_add_entities(entities)


class WorkshiftSensor(WorkshiftEntityMixin, SensorEntity):
    """Represents a Workshift numeric sensor."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, runtime: WorkshiftRuntimeData, sensor_type: str) -> None:
        super().__init__(entry, runtime, sensor_type)
        self._sensor_type = sensor_type
        self._attr_translation_key = sensor_type

    @property
    def native_value(self) -> int:
        info = self._get_shift_info()
        if info is None:
            return 0
        return info.shift_index

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        info = self._get_shift_info()
        is_workday = self._is_workday()
        if info is None:
            return {
                "shift_index": None,
                "start_datetime": None,
                "end_datetime": None,
                "start_time": None,
                "end_time": None,
                "description": None,
                "is_workday": is_workday,
            }
        attrs = _build_attributes(info)
        attrs["is_workday"] = is_workday
        return attrs

    def _get_shift_info(self) -> Optional[WorkshiftInfo]:
        if self._sensor_type == SENSOR_TODAY:
            return self._runtime.today_shift
        if self._sensor_type == SENSOR_TOMORROW:
            return self._runtime.tomorrow_shift
        return None

    def _is_workday(self) -> bool:
        if self._sensor_type == SENSOR_TODAY:
            return self._runtime.today_is_workday
        if self._sensor_type == SENSOR_TOMORROW:
            return self._runtime.tomorrow_is_workday
        return False


def _build_attributes(info: WorkshiftInfo) -> Dict[str, Any]:
    return {
        "shift_index": info.shift_index,
        "start_datetime": info.start.isoformat(),
        "end_datetime": info.end.isoformat(),
        "start_time": info.start.strftime("%H:%M"),
        "end_time": info.end.strftime("%H:%M"),
        "description": f"Shift {info.shift_index}",
    }
