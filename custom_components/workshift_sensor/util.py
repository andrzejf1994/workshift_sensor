"""Utility helpers for the Workshift Sensor integration."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
import logging
from typing import Any, Iterable, Mapping

from homeassistant.const import CONF_NAME

from .const import (
    CONF_NUM_SHIFTS,
    CONF_SCHEDULE,
    CONF_SCHEDULE_START,
    CONF_SHIFT_DURATION,
    CONF_START_TIMES,
    CONF_USE_WORKDAY_SENSOR,
    CONF_WORKDAY_SENSOR,
    CONF_WORKDAY_SENSOR_TOMORROW,
    DEFAULT_NAME,
    DEFAULT_NUM_SHIFTS,
    DEFAULT_SHIFT_DURATION,
    MAX_SHIFTS,
)

_LOGGER = logging.getLogger(__name__)


def _sanitize_name(value: Any, fallback: str = DEFAULT_NAME) -> str:
    if isinstance(value, str):
        candidate = value.strip()
    elif value is None:
        candidate = fallback
    else:
        candidate = str(value).strip()
    return candidate


def _sanitize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "on", "1", "yes"}:
            return True
        if lowered in {"false", "off", "0", "no"}:
            return False
    return default


def _coerce_int(value: Any, *, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    if minimum is not None and number < minimum:
        number = minimum
    if maximum is not None and number > maximum:
        number = maximum
    return number


def _sanitize_start_times(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        items: Iterable[Any] = value
    elif isinstance(value, str):
        if "," in value:
            items = (part.strip() for part in value.split(","))
        elif value.strip():
            items = (value.strip(),)
        else:
            items = ()
    else:
        items = ()

    sanitized: list[str] = []
    for item in items:
        if isinstance(item, str):
            candidate = item.strip()
        elif item is None:
            continue
        else:
            candidate = str(item).strip()
        if candidate:
            sanitized.append(candidate)
        if len(sanitized) >= MAX_SHIFTS:
            break
    return tuple(sanitized)


@dataclass(frozen=True)
class WorkshiftConfigData:
    """Immutable representation of configuration values."""

    name: str = DEFAULT_NAME
    use_workday_sensor: bool = True
    workday_sensor: str | None = None
    workday_sensor_tomorrow: str | None = None
    shift_duration: int = DEFAULT_SHIFT_DURATION
    num_shifts: int = DEFAULT_NUM_SHIFTS
    start_times: tuple[str, ...] = ()
    schedule_start: str | None = None
    schedule: str = ""

    @classmethod
    def from_mapping(
        cls, mapping: Mapping[str, Any], *, fallback_name: str = DEFAULT_NAME
    ) -> "WorkshiftConfigData":
        name = _sanitize_name(mapping.get(CONF_NAME, fallback_name), fallback=fallback_name)
        shift_duration = _coerce_int(
            mapping.get(CONF_SHIFT_DURATION),
            default=DEFAULT_SHIFT_DURATION,
            minimum=1,
        )
        num_shifts = _coerce_int(
            mapping.get(CONF_NUM_SHIFTS),
            default=DEFAULT_NUM_SHIFTS,
            minimum=1,
            maximum=MAX_SHIFTS,
        )
        start_times = _sanitize_start_times(mapping.get(CONF_START_TIMES))
        use_workday = _coerce_bool(
            mapping.get(CONF_USE_WORKDAY_SENSOR),
            default=True,
        )
        schedule_start = _sanitize_optional_str(mapping.get(CONF_SCHEDULE_START))
        schedule = _sanitize_name(mapping.get(CONF_SCHEDULE, ""), fallback="")

        return cls(
            name=name,
            use_workday_sensor=use_workday,
            workday_sensor=_sanitize_optional_str(mapping.get(CONF_WORKDAY_SENSOR)),
            workday_sensor_tomorrow=_sanitize_optional_str(
                mapping.get(CONF_WORKDAY_SENSOR_TOMORROW)
            ),
            shift_duration=shift_duration,
            num_shifts=num_shifts,
            start_times=start_times,
            schedule_start=schedule_start,
            schedule=schedule,
        )

    def with_updates(self, **changes: Any) -> "WorkshiftConfigData":
        """Return a copy with provided updates."""
        return replace(self, **changes)

    def ensure_start_times(self) -> "WorkshiftConfigData":
        """Ensure the number of start times matches the configured shifts."""
        if len(self.start_times) == self.num_shifts:
            return self
        start_times = list(self.start_times)
        if len(start_times) > self.num_shifts:
            start_times = start_times[: self.num_shifts]
        else:
            if start_times:
                seed_time = start_times[-1]
            else:
                seed_time = "06:00"
            try:
                base_time = datetime.strptime(seed_time, "%H:%M")
            except ValueError:
                base_time = datetime.strptime("06:00", "%H:%M")
            if not start_times:
                base_time = base_time - timedelta(hours=self.shift_duration)
            for _ in range(len(start_times), self.num_shifts):
                base_time = base_time + timedelta(hours=self.shift_duration)
                start_times.append(base_time.strftime("%H:%M"))
        return self.with_updates(start_times=tuple(start_times))

    def as_dict(self) -> dict[str, Any]:
        """Convert to a Home Assistant config entry friendly dictionary."""
        data: dict[str, Any] = {
            CONF_NAME: self.name,
            CONF_USE_WORKDAY_SENSOR: self.use_workday_sensor,
            CONF_SHIFT_DURATION: self.shift_duration,
            CONF_NUM_SHIFTS: self.num_shifts,
            CONF_START_TIMES: list(self.start_times),
            CONF_SCHEDULE: self.schedule,
        }
        if self.schedule_start:
            data[CONF_SCHEDULE_START] = self.schedule_start
        if self.workday_sensor:
            data[CONF_WORKDAY_SENSOR] = self.workday_sensor
        if self.workday_sensor_tomorrow:
            data[CONF_WORKDAY_SENSOR_TOMORROW] = self.workday_sensor_tomorrow
        return data

    @property
    def schedule_start_date(self) -> date | None:
        if not self.schedule_start:
            return None
        try:
            return date.fromisoformat(self.schedule_start)
        except ValueError:
            _LOGGER.warning("Invalid schedule_start '%s', ignoring", self.schedule_start)
            return None

    @property
    def start_times_as_time(self) -> tuple[time, ...]:
        parsed: list[time] = []
        for item in self.start_times:
            try:
                parsed.append(datetime.strptime(item, "%H:%M").time())
            except ValueError:
                _LOGGER.debug("Ignoring invalid start time '%s'", item)
        return tuple(parsed)

    @property
    def pattern_length(self) -> int:
        return len(self.schedule)
