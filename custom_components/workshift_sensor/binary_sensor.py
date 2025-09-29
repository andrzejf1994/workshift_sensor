"""Binary sensor for the Workshift Sensor integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .schedule import WorkshiftSchedule
from .util import WorkshiftConfigData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the active shift binary sensor."""
    config: WorkshiftConfigData = hass.data[DOMAIN][entry.entry_id]
    entity = WorkshiftActiveSensor(hass, entry, config)
    async_add_entities([entity], update_before_add=True)


class WorkshiftActiveSensor(BinarySensorEntity):
    """Binary sensor indicating whether a shift is currently active."""

    _attr_should_poll = False

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, config: WorkshiftConfigData
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._config = config
        self._schedule = WorkshiftSchedule(config)
        name_prefix = config.name or entry.title or "Workshift"
        self._attr_name = f"{name_prefix} Active"
        self._attr_unique_id = f"{entry.entry_id}_active"
        self._attr_is_on = False
        self._timer_cancel: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        reference = dt_util.now()
        self._attr_is_on = self._is_shift_active(reference)
        self._schedule_next_event(reference)
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None

    def _is_shift_active(self, reference: datetime) -> bool:
        reference_local = dt_util.as_local(reference)
        today = reference_local.date()
        code_today = self._schedule.shift_code(self.hass, today, today=today)
        if code_today > 0:
            start_dt = self._schedule.start_datetime(today, code_today - 1)
            end_dt = start_dt + self._schedule.duration()
            if start_dt <= reference_local < end_dt:
                return True
        yesterday = today - timedelta(days=1)
        code_yesterday = self._schedule.shift_code(self.hass, yesterday, today=today)
        if code_yesterday > 0:
            start_dt = self._schedule.start_datetime(yesterday, code_yesterday - 1)
            end_dt = start_dt + self._schedule.duration()
            if end_dt.date() == today and reference_local < end_dt:
                return True
        return False

    def _schedule_next_event(self, reference: datetime | None = None) -> None:
        if self._timer_cancel:
            self._timer_cancel()
            self._timer_cancel = None
        if reference is None:
            reference = dt_util.now()
        reference_local = dt_util.as_local(reference)
        today = reference_local.date()
        target_time: datetime | None = None

        if self._attr_is_on:
            code_today = self._schedule.shift_code(self.hass, today, today=today)
            if code_today > 0:
                start_dt = self._schedule.start_datetime(today, code_today - 1)
                end_dt = start_dt + self._schedule.duration()
                if reference_local < end_dt:
                    target_time = end_dt
            if target_time is None:
                yesterday = today - timedelta(days=1)
                code_yesterday = self._schedule.shift_code(
                    self.hass, yesterday, today=today
                )
                if code_yesterday > 0:
                    start_dt = self._schedule.start_datetime(yesterday, code_yesterday - 1)
                    end_dt = start_dt + self._schedule.duration()
                    if reference_local < end_dt:
                        target_time = end_dt
        else:
            code_today = self._schedule.shift_code(self.hass, today, today=today)
            if code_today > 0:
                start_dt = self._schedule.start_datetime(today, code_today - 1)
                if reference_local < start_dt:
                    target_time = start_dt
            if target_time is None and self._schedule.pattern_length > 0:
                for days_ahead in range(1, self._schedule.pattern_length + 1):
                    future_day = today + timedelta(days=days_ahead)
                    code_future = self._schedule.shift_code(
                        self.hass, future_day, today=today
                    )
                    if code_future > 0:
                        start_dt = self._schedule.start_datetime(
                            future_day, code_future - 1
                        )
                        if start_dt > reference_local:
                            target_time = start_dt
                            break

        if target_time is None:
            return

        _LOGGER.debug("Scheduling next state change at %s", target_time)
        self._timer_cancel = async_track_point_in_time(
            self.hass, self._timer_trigger, dt_util.as_utc(target_time)
        )

    @callback
    def _timer_trigger(self, _now: datetime) -> None:
        self._attr_is_on = self._is_shift_active(dt_util.now())
        self.async_write_ha_state()
        self._schedule_next_event()

    @property
    def device_info(self) -> DeviceInfo:
        name = self._config.name or self._entry.title or "Workshift"
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=name,
            manufacturer="Workshift Sensor",
        )
