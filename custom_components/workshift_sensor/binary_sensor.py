"""Binary sensor platform for Workshift Sensor."""
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WorkshiftEntityMixin, WorkshiftRuntimeData
from .const import BINARY_SENSOR_ON_SHIFT, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Workshift binary sensors for a config entry."""

    runtime: WorkshiftRuntimeData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WorkshiftOnShiftBinarySensor(entry, runtime)])


class WorkshiftOnShiftBinarySensor(WorkshiftEntityMixin, BinarySensorEntity):
    """Binary sensor indicating if a shift is currently active."""

    _attr_device_class = "occupancy"

    def __init__(self, entry: ConfigEntry, runtime: WorkshiftRuntimeData) -> None:
        super().__init__(entry, runtime, BINARY_SENSOR_ON_SHIFT)
        self._attr_translation_key = BINARY_SENSOR_ON_SHIFT

    @property
    def is_on(self) -> bool:
        return self._runtime.current_shift is not None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        info = self._runtime.current_shift
        if not info:
            return {
                "shift_index": None,
                "start_datetime": None,
                "end_datetime": None,
                "is_workday": self._runtime.today_is_workday,
            }
        return {
            "shift_index": info.shift_index,
            "start_datetime": info.start.isoformat(),
            "end_datetime": info.end.isoformat(),
            "is_workday": self._runtime.today_is_workday,
        }
