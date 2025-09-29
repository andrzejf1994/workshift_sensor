"""Workshift Sensor integration setup."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, dt_util
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import slugify

from .const import (
    CONF_ENTRY_NAME,
    CONF_SCHEDULE_START_DATE,
    CONF_SCHEDULE_STRING,
    CONF_SHIFT_HOURS,
    CONF_SHIFT_STARTS,
    CONF_SHIFTS_PER_DAY,
    CONF_USE_WORKDAY_SENSOR,
    CONF_WORKDAY_ENTITY_TODAY,
    CONF_WORKDAY_ENTITY_TOMORROW,
    DEVICE_MANUFACTURER,
    DOMAIN,
    PLATFORMS,
    WorkshiftConfigData,
    WorkshiftInfo,
    WorkshiftSchedule,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class WorkshiftRuntimeData:
    """Runtime data stored per config entry."""

    config: WorkshiftConfigData
    schedule: WorkshiftSchedule
    listeners: List[Callable[[], None]]
    cancel_callback: Optional[Callable[[], None]]

    today_shift: Optional[WorkshiftInfo] = None
    tomorrow_shift: Optional[WorkshiftInfo] = None
    current_shift: Optional[WorkshiftInfo] = None
    today_is_workday: bool = True
    tomorrow_is_workday: bool = True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Workshift Sensor integration (YAML not supported)."""

    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Workshift Sensor from a config entry."""

    try:
        config_data = _config_entry_to_data(entry)
    except ValueError as err:
        raise ConfigEntryNotReady(str(err)) from err

    runtime = WorkshiftRuntimeData(
        config=config_data,
        schedule=WorkshiftSchedule(config_data),
        listeners=[],
        cancel_callback=None,
    )
    hass.data[DOMAIN][entry.entry_id] = runtime

    await _async_register_device(hass, entry, config_data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_start_scheduler(hass, entry, runtime)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        runtime: WorkshiftRuntimeData = hass.data[DOMAIN].pop(entry.entry_id)
        if runtime.cancel_callback:
            runtime.cancel_callback()
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle entry updates by reloading."""

    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_device(
    hass: HomeAssistant, entry: ConfigEntry, config: WorkshiftConfigData
) -> None:
    """Ensure a device is present for the entry."""

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=config.entry_name,
        manufacturer=DEVICE_MANUFACTURER,
    )


def _config_entry_to_data(entry: ConfigEntry) -> WorkshiftConfigData:
    """Create config data object from entry data and options."""

    raw: Dict[str, Any] = {**entry.data, **entry.options}
    try:
        shift_hours = int(raw[CONF_SHIFT_HOURS])
        shifts_per_day = int(raw[CONF_SHIFTS_PER_DAY])
        shift_starts = _parse_shift_starts(raw[CONF_SHIFT_STARTS], shifts_per_day)
        schedule_start_date = date.fromisoformat(raw[CONF_SCHEDULE_START_DATE])
        schedule_string = str(raw[CONF_SCHEDULE_STRING])
    except (KeyError, ValueError) as err:
        raise ValueError("Invalid configuration data") from err

    return WorkshiftConfigData(
        entry_name=str(raw[CONF_ENTRY_NAME]),
        use_workday_sensor=bool(raw.get(CONF_USE_WORKDAY_SENSOR, False)),
        workday_entity_today=raw.get(CONF_WORKDAY_ENTITY_TODAY),
        workday_entity_tomorrow=raw.get(CONF_WORKDAY_ENTITY_TOMORROW),
        shift_hours=shift_hours,
        shifts_per_day=shifts_per_day,
        shift_starts=shift_starts,
        schedule_start_date=schedule_start_date,
        schedule_string=schedule_string,
    )


def _parse_shift_starts(starts: List[str], shifts_per_day: int) -> List[time]:
    """Parse a list of HH:MM strings to time objects."""

    from datetime import datetime as dt

    if len(starts) != shifts_per_day:
        raise ValueError("Invalid number of shift start times")

    parsed: List[datetime.time] = []
    last_minutes: Optional[int] = None
    for start_str in starts:
        try:
            parsed_time = dt.strptime(start_str, "%H:%M").time()
        except ValueError as err:
            raise ValueError(f"Invalid time format: {start_str}") from err
        minutes = parsed_time.hour * 60 + parsed_time.minute
        if last_minutes is not None and minutes <= last_minutes:
            raise ValueError("Shift start times must be in ascending order")
        last_minutes = minutes
        parsed.append(parsed_time)
    return parsed


def _async_start_scheduler(
    hass: HomeAssistant, entry: ConfigEntry, runtime: WorkshiftRuntimeData
) -> None:
    """Calculate initial state and schedule updates."""

    _async_update_state(hass, entry, runtime)


@callback
def _async_update_state(
    hass: HomeAssistant,
    entry: Optional[ConfigEntry],
    runtime: WorkshiftRuntimeData,
) -> None:
    """Update runtime state and notify listeners."""

    now = dt_util.now()
    tz = hass.config.time_zone
    if tz is None:
        _LOGGER.warning("Timezone is not configured; defaulting to UTC")

    runtime.today_shift = _resolve_shift_for_day(
        hass, runtime.config, runtime.schedule, now.date(), is_tomorrow=False
    )
    runtime.tomorrow_shift = _resolve_shift_for_day(
        hass,
        runtime.config,
        runtime.schedule,
        (now + timedelta(days=1)).date(),
        is_tomorrow=True,
    )
    runtime.today_is_workday = runtime.today_shift is not None
    runtime.tomorrow_is_workday = runtime.tomorrow_shift is not None
    runtime.current_shift = _resolve_current_shift(
        hass, runtime.config, runtime.schedule, now
    )

    _LOGGER.debug(
        "Entry %s updated: today=%s tomorrow=%s current=%s",
        entry.entry_id if entry else runtime.config.entry_name,
        runtime.today_shift,
        runtime.tomorrow_shift,
        runtime.current_shift,
    )

    for listener in list(runtime.listeners):
        listener()

    _schedule_next_update(hass, entry, runtime, now)


def _resolve_shift_for_day(
    hass: HomeAssistant,
    config: WorkshiftConfigData,
    schedule: WorkshiftSchedule,
    target_date: date,
    *,
    is_tomorrow: bool = False,
) -> Optional[WorkshiftInfo]:
    """Resolve shift info for a given day considering workday sensors."""

    is_workday = _is_workday_for_date(
        hass, config, target_date, True, is_tomorrow=is_tomorrow
    )
    if not is_workday:
        return None

    shift_info = schedule.get_shift_info(target_date)
    if shift_info is None:
        return None

    return _localize_shift_info(shift_info, target_date, config)


def _resolve_current_shift(
    hass: HomeAssistant,
    config: WorkshiftConfigData,
    schedule: WorkshiftSchedule,
    now: datetime,
) -> Optional[WorkshiftInfo]:
    """Determine if a shift is active at the current time."""

    today = now.date()
    info_today = _resolve_shift_for_day(
        hass, config, schedule, today, is_tomorrow=False
    )
    if info_today and info_today.start <= now < info_today.end:
        return info_today

    yesterday = today - timedelta(days=1)
    info_yesterday = schedule.get_shift_info(yesterday)
    if info_yesterday is None:
        return None
    info_yesterday = _localize_shift_info(info_yesterday, yesterday, config)
    if info_yesterday.start <= now < info_yesterday.end:
        if not config.use_workday_sensor:
            return info_yesterday
        # Verify yesterday was considered a workday if sensors apply
        if _is_workday_for_date(
            hass, config, yesterday, True, is_tomorrow=False
        ):
            return info_yesterday
    return None


def _localize_shift_info(
    shift_info: WorkshiftInfo,
    target_date: date,
    config: WorkshiftConfigData,
) -> WorkshiftInfo:
    """Localize naive shift info datetimes."""

    base = dt_util.start_of_local_day(datetime.combine(target_date, time.min))
    start = base.replace(
        hour=shift_info.start.hour,
        minute=shift_info.start.minute,
        second=0,
        microsecond=0,
    )
    end = start + timedelta(hours=config.shift_hours)
    return WorkshiftInfo(shift_index=shift_info.shift_index, start=start, end=end)


def _is_workday_for_date(
    hass: HomeAssistant,
    config: WorkshiftConfigData,
    target_date: date,
    default: bool,
    *,
    is_tomorrow: bool,
) -> bool:
    """Evaluate workday sensor state for a given date."""

    if not config.use_workday_sensor:
        return True

    entity_id = config.workday_entity_tomorrow if is_tomorrow else config.workday_entity_today
    if entity_id:
        state = hass.states.get(entity_id)
        if state is None:
            _LOGGER.warning("Workday sensor %s not found", entity_id)
            return default
        if state.state in ("on", "true", "1", True):
            return True
        if state.state in ("off", "false", "0", False):
            return False
        attr_key = "tomorrow" if is_tomorrow else "today"
        forecast = state.attributes.get(attr_key)
        if isinstance(forecast, bool):
            return forecast
        return default

    # Fall back to today's sensor forecast if tomorrow specific sensor missing
    if is_tomorrow and config.workday_entity_today:
        state = hass.states.get(config.workday_entity_today)
        if state:
            for key in ("tomorrow", "next_day", "next_workday"):
                forecast = state.attributes.get(key)
                if isinstance(forecast, bool):
                    return forecast
    return True


def _schedule_next_update(
    hass: HomeAssistant,
    entry: Optional[ConfigEntry],
    runtime: WorkshiftRuntimeData,
    now: datetime,
) -> None:
    """Schedule the next automatic update based on upcoming shift boundaries."""

    times: List[datetime] = []
    for info in (
        runtime.today_shift,
        runtime.tomorrow_shift,
        runtime.current_shift,
    ):
        if info:
            times.extend([info.start, info.end])

    # Always schedule for the next midnight to refresh the schedule
    next_midnight = dt_util.start_of_local_day(now + timedelta(days=1))
    times.append(next_midnight)

    next_time = min((t for t in times if t and t > now + timedelta(seconds=5)), default=None)

    if runtime.cancel_callback:
        runtime.cancel_callback()
        runtime.cancel_callback = None

    if next_time is None:
        next_time = now + timedelta(minutes=5)

    _LOGGER.debug("Scheduling next update at %s", next_time)

    runtime.cancel_callback = async_track_point_in_time(
        hass,
        lambda _: _async_update_state(hass, entry, runtime),
        next_time,
    )


class WorkshiftEntityMixin:
    """Mixin shared by all workshift entities."""

    def __init__(self, entry: ConfigEntry, runtime: WorkshiftRuntimeData, entity_type: str) -> None:
        self._entry = entry
        self._runtime = runtime
        self._entity_type = entity_type
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        slug = slugify(runtime.config.entry_name)
        self._attr_unique_id = f"{slug}-{entity_type}-{entry.entry_id[:8]}"

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": self._runtime.config.entry_name,
            "manufacturer": DEVICE_MANUFACTURER,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.async_write_ha_state not in self._runtime.listeners:
            self._runtime.listeners.append(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self.async_write_ha_state in self._runtime.listeners:
            self._runtime.listeners.remove(self.async_write_ha_state)
