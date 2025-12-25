from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Optional
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import UTC

from . import DOMAIN
from .schedule import ShiftInstance, WorkshiftSchedule

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up the workshift calendar entity."""
    data = hass.data[DOMAIN][entry.entry_id]
    base_name = data.get("name", "Workshift")
    name_prefix = data.get("name_prefix") or base_name
    async_add_entities([WorkshiftCalendarEntity(hass, entry, base_name, name_prefix)])


class WorkshiftCalendarEntity(CalendarEntity):
    """Calendar entity exposing dynamic workshift events."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry, base_name: str, name_prefix: str):
        self.hass = hass
        self._entry = entry
        self._config = hass.data[DOMAIN][entry.entry_id]
        self._schedule = WorkshiftSchedule(hass, self._config)
        self._attr_name = f"{name_prefix} Schedule"
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._cancel_refresh: Optional[Callable[[], None]] = None
        self._attr_event: CalendarEvent | None = None
        self._device_name = base_name

    async def async_added_to_hass(self):
        """Initialize state and schedule refreshes."""
        self._refresh()

    async def async_will_remove_from_hass(self):
        """Tear down timers."""
        if self._cancel_refresh:
            self._cancel_refresh()
            self._cancel_refresh = None

    @callback
    def _refresh(self, *_):
        """Update the current/next event and plan the following refresh."""
        self._attr_event = self._compute_current_event()
        self.async_write_ha_state()
        self._schedule_refresh()

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next calendar event."""
        return self._attr_event

    def _compute_current_event(self) -> CalendarEvent | None:
        """Compute the ongoing or next upcoming shift event."""
        now = dt_util.now(self._schedule.tz)
        active_shift = self._schedule.shift_covering(now)
        if active_shift:
            return self._format_event(active_shift)

        upcoming_shift = self._schedule.next_shift_after(now)
        if upcoming_shift:
            return self._format_event(upcoming_shift)
        return None

    def _schedule_refresh(self) -> None:
        """Schedule state refresh at the next relevant moment."""
        if self._cancel_refresh:
            self._cancel_refresh()
            self._cancel_refresh = None

        now = dt_util.now(self._schedule.tz)
        target = None
        if self._attr_event:
            if self._attr_event.start <= now < self._attr_event.end:
                target = self._attr_event.end
            elif self._attr_event.start > now:
                target = self._attr_event.start

        if target is None:
            target = dt_util.start_of_local_day(now + timedelta(days=1))
        self._cancel_refresh = async_track_point_in_utc_time(
            self.hass,
            self._refresh,
            dt_util.as_utc(target + timedelta(seconds=1)),
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        """Return dynamically generated events within a time range."""
        start = self._ensure_local(start_date)
        end = self._ensure_local(end_date)
        events: list[CalendarEvent] = []

        start_day = start.date()
        end_day = end.date()
        total_days = (end_day - start_day).days
        for offset in range(-1, total_days + 2):
            day = start_day + timedelta(days=offset)
            shift = self._schedule.get_shift(day)
            if shift is None:
                continue
            if shift.end <= start or shift.start >= end:
                continue
            events.append(self._format_event(shift))
        return events

    def _format_event(self, shift: ShiftInstance) -> CalendarEvent:
        """Convert a shift instance to a CalendarEvent."""
        description = (
            f"Integration: {DOMAIN}\n"
            f"Schedule: {self._config.get('schedule', '')}\n"
            f"Rotation index: {shift.rotation_index if shift.rotation_index is not None else '-'}"
        )
        summary = self._schedule.shift_name(shift.code)
        return CalendarEvent(
            summary=summary,
            start=shift.start,
            end=shift.end,
            description=description,
        )

    def _ensure_local(self, dt_value: datetime) -> datetime:
        """Normalize provided datetime to the integration timezone."""
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=UTC)
        return dt_value.astimezone(self._schedule.tz)

    @property
    def extra_state_attributes(self) -> dict:
        """Expose metadata about the calendar."""
        return {
            "integration": DOMAIN,
            "schedule": self._config.get("schedule", ""),
            "schedule_start": self._config.get("schedule_start"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information for this entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._device_name,
            manufacturer="Workshift Sensor",
        )
