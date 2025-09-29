"""Sensor entities for the Workshift Sensor integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .schedule import WorkshiftSchedule
from .util import WorkshiftConfigData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the day sensors for a config entry."""
    config: WorkshiftConfigData = hass.data[DOMAIN][entry.entry_id]
    schedule = WorkshiftSchedule(config)
    name = config.name or entry.title or "Workshift"
    entities: list[WorkshiftDaySensor] = [
        WorkshiftDaySensor(hass, entry, config, schedule, name, 0),
        WorkshiftDaySensor(hass, entry, config, schedule, name, 1),
    ]
    async_add_entities(entities, update_before_add=True)


class WorkshiftDaySensor(SensorEntity):
    """Sensor showing the active shift for today or tomorrow."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        config: WorkshiftConfigData,
        schedule: WorkshiftSchedule,
        name_prefix: str,
        offset: int,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._config = config
        self._schedule = schedule
        self._offset = offset
        suffix = "today" if offset == 0 else "tomorrow"
        self._attr_name = f"{name_prefix} {suffix.title()}"
        self._attr_unique_id = f"{entry.entry_id}_day_{suffix}"
        self._attr_extra_state_attributes = {
            "shift_start": None,
            "shift_end": None,
        }
        self._midnight_unsub: Callable[[], None] | None = None
        self._workday_unsub: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Register listeners when the entity is added."""
        reference = dt_util.now()
        self._update_state(reference)
        self.async_write_ha_state()

        next_midnight = dt_util.start_of_local_day(reference.date() + timedelta(days=1))

        @callback
        def _midnight_callback(trigger_time: datetime) -> None:
            self._update_state(dt_util.now())
            self.async_write_ha_state()
            self._midnight_unsub = async_track_point_in_time(
                self.hass,
                _midnight_callback,
                dt_util.as_utc(trigger_time + timedelta(days=1)),
            )

        self._midnight_unsub = async_track_point_in_time(
            self.hass, _midnight_callback, dt_util.as_utc(next_midnight)
        )

        entities: set[str] = set()
        if self._config.use_workday_sensor:
            if self._config.workday_sensor:
                entities.add(self._config.workday_sensor)
            tomorrow = self._config.workday_sensor_tomorrow or self._config.workday_sensor
            if tomorrow:
                entities.add(tomorrow)

        if entities:

            @callback
            def _workday_state_change(_event) -> None:
                self._update_state(dt_util.now())
                self.async_write_ha_state()

            self._workday_unsub = async_track_state_change_event(
                self.hass,
                list(entities),
                _workday_state_change,
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._midnight_unsub:
            self._midnight_unsub()
            self._midnight_unsub = None
        if self._workday_unsub:
            self._workday_unsub()
            self._workday_unsub = None

    def _update_state(self, reference: datetime) -> None:
        reference_local = dt_util.as_local(reference)
        today = reference_local.date()
        target_day = today + timedelta(days=self._offset)
        code = self._schedule.shift_code(self.hass, target_day, today=today)
        if code <= 0:
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {
                "shift_start": None,
                "shift_end": None,
            }
            return

        start_dt = self._schedule.start_datetime(target_day, code - 1)
        end_dt = start_dt + self._schedule.duration()
        self._attr_native_value = code
        self._attr_extra_state_attributes = {
            "shift_start": dt_util.as_utc(start_dt).isoformat(),
            "shift_end": dt_util.as_utc(end_dt).isoformat(),
        }

    @property
    def device_info(self) -> DeviceInfo:
        name = self._config.name or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )