from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.selector as selector

from . import DOMAIN

# Configuration keys
CONF_WORKDAY_SENSOR = "workday_sensor"
CONF_WORKDAY_SENSOR_TOMORROW = "workday_sensor_tomorrow"
CONF_USE_WORKDAY_SENSOR = "use_workday_sensor"
CONF_SHIFT_DURATION = "shift_duration"
CONF_NUM_SHIFTS = "num_shifts"
CONF_START_TIMES = "start_times"
CONF_SCHEDULE_START = "schedule_start"
CONF_SCHEDULE = "schedule"


def _default_last_monday() -> str:
    today = date.today()
    days_since = today.weekday()
    last_monday = today - timedelta(days=days_since)
    return last_monday.strftime("%Y-%m-%d")


def _sanitize_optional(value: Any) -> Any:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _user_schema(data: dict[str, Any]) -> vol.Schema:
    default_name = data.get(CONF_NAME, "")
    default_use_workday = data.get(CONF_USE_WORKDAY_SENSOR, True)
    default_workday = data.get(CONF_WORKDAY_SENSOR)
    if default_workday is None:
        default_workday = "binary_sensor.workday_sensor"
    default_tomorrow = data.get(CONF_WORKDAY_SENSOR_TOMORROW) or default_workday

    fields: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=default_name): selector.TextSelector(),
        vol.Required(CONF_USE_WORKDAY_SENSOR, default=default_use_workday): selector.BooleanSelector(),
        vol.Optional(CONF_WORKDAY_SENSOR, default=default_workday): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor")
        ),
        vol.Optional(CONF_WORKDAY_SENSOR_TOMORROW, default=default_tomorrow): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="binary_sensor")
        ),
    }
    return vol.Schema(fields)


def _shift_schema(data: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SHIFT_DURATION, default=data.get(CONF_SHIFT_DURATION, 8)): vol.Coerce(int),
            vol.Required(CONF_NUM_SHIFTS, default=data.get(CONF_NUM_SHIFTS, 3)): vol.Coerce(int),
        }
    )


def _start_times_schema(data: dict[str, Any]) -> vol.Schema:
    num_shifts = int(data.get(CONF_NUM_SHIFTS, 1))
    defaults: list[str] = list(data.get(CONF_START_TIMES, []))
    duration = int(data.get(CONF_SHIFT_DURATION, 8))
    base = datetime.strptime("06:00", "%H:%M")
    fields: dict[Any, Any] = {}
    for i in range(1, num_shifts + 1):
        if i - 1 < len(defaults):
            default = defaults[i - 1]
        else:
            default = (base + timedelta(hours=duration * (i - 1))).strftime("%H:%M")
        fields[vol.Required(f"{CONF_START_TIMES}_{i}", default=default)] = str
    return vol.Schema(fields)


def _schedule_schema(data: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SCHEDULE_START,
                default=data.get(CONF_SCHEDULE_START, _default_last_monday()),
            ): str,
            vol.Required(CONF_SCHEDULE, default=data.get(CONF_SCHEDULE, "")): str,
        }
    )


def _start_times_sorted(times: Iterable[str]) -> bool:
    minutes: list[int] = []
    for value in times:
        hour, minute = value.split(":")
        minutes.append(int(hour) * 60 + int(minute))
    return all(curr > prev for prev, curr in zip(minutes, minutes[1:]))


def _name_in_use(hass: HomeAssistant, name: str, *, exclude_entry_id: str | None = None) -> bool:
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        existing_name = (
            entry.options.get(CONF_NAME)
            or entry.data.get(CONF_NAME)
            or entry.title
        )
        if existing_name == name:
            return True
    return False


class WorkshiftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._reconfigure_entry_id: str | None = None
        self._reconfigure_loaded = False

    def _initialize_from_entry(self) -> None:
        if self._reconfigure_loaded or self._reconfigure_entry_id is None:
            return
        entry = self.hass.config_entries.async_get_entry(self._reconfigure_entry_id)
        if entry is None:
            return
        data = dict(entry.data)
        if entry.options:
            data.update(entry.options)
        self._data = data
        self._reconfigure_loaded = True

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {**self._data, **user_input}
            candidate[CONF_NAME] = candidate.get(CONF_NAME, "").strip()
            if not candidate[CONF_NAME]:
                errors["base"] = "invalid_name"
            elif _name_in_use(
                self.hass,
                candidate[CONF_NAME],
                exclude_entry_id=self._reconfigure_entry_id,
            ):
                errors["base"] = "name_exists"
            elif (
                candidate.get(CONF_USE_WORKDAY_SENSOR, True)
                and not candidate.get(CONF_WORKDAY_SENSOR)
            ):
                errors["base"] = "workday_required"
            if not errors:
                self._data[CONF_NAME] = candidate[CONF_NAME]
                self._data[CONF_USE_WORKDAY_SENSOR] = candidate.get(CONF_USE_WORKDAY_SENSOR, True)
                self._data[CONF_WORKDAY_SENSOR] = _sanitize_optional(candidate.get(CONF_WORKDAY_SENSOR))
                self._data[CONF_WORKDAY_SENSOR_TOMORROW] = _sanitize_optional(
                    candidate.get(CONF_WORKDAY_SENSOR_TOMORROW)
                )
                return await self.async_step_shifts()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._data),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        if self._reconfigure_entry_id is None:
            entry_id = self.context.get("entry_id")
            if entry_id is None:
                return self.async_abort(reason="unknown_entry")
            self._reconfigure_entry_id = entry_id

        self._initialize_from_entry()

        if not self._reconfigure_loaded:
            return self.async_abort(reason="unknown_entry")

        return await self.async_step_user(user_input)

    async def async_step_shifts(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            duration = int(user_input.get(CONF_SHIFT_DURATION, 0))
            num = int(user_input.get(CONF_NUM_SHIFTS, 0))
            if duration <= 0:
                errors["base"] = "invalid_shift_duration"
            elif num < 1 or num > 9:
                errors["base"] = "invalid_num_shifts"
            if not errors:
                self._data[CONF_SHIFT_DURATION] = duration
                self._data[CONF_NUM_SHIFTS] = num
                return await self.async_step_start_times()

        return self.async_show_form(
            step_id="shifts",
            data_schema=_shift_schema(self._data),
            errors=errors,
        )

    async def async_step_start_times(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            num_shifts = int(self._data.get(CONF_NUM_SHIFTS, 1))
            times: list[str] = []
            for i in range(1, num_shifts + 1):
                value = user_input.get(f"{CONF_START_TIMES}_{i}")
                try:
                    datetime.strptime(value, "%H:%M")
                except (TypeError, ValueError):
                    errors["base"] = "invalid_time_format"
                    break
                times.append(value)
            if not errors and not _start_times_sorted(times):
                errors["base"] = "times_not_sorted"
            if not errors:
                self._data[CONF_START_TIMES] = times
                return await self.async_step_schedule()

        return self.async_show_form(
            step_id="start_times",
            data_schema=_start_times_schema(self._data),
            errors=errors,
        )

    async def async_step_schedule(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            date_str = user_input.get(CONF_SCHEDULE_START)
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                errors["base"] = "invalid_date"
            sched = user_input.get(CONF_SCHEDULE, "")
            if sched and (
                not sched.isdigit()
                or any(int(ch) > self._data.get(CONF_NUM_SHIFTS, 1) for ch in sched)
            ):
                errors["base"] = "invalid_schedule"
            if not errors:
                self._data[CONF_SCHEDULE_START] = date_str
                self._data[CONF_SCHEDULE] = sched
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        return self.async_show_form(
            step_id="schedule",
            data_schema=_schedule_schema(self._data),
            errors=errors,
            description_placeholders={"max": self._data.get(CONF_NUM_SHIFTS, 1)},
        )


class WorkshiftOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._data: dict[str, Any] = {**config_entry.data, **config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = {**self._data, **user_input}
            candidate[CONF_NAME] = candidate.get(CONF_NAME, "").strip()
            if not candidate[CONF_NAME]:
                errors["base"] = "invalid_name"
            elif _name_in_use(
                self.hass,
                candidate[CONF_NAME],
                exclude_entry_id=self.config_entry.entry_id,
            ):
                errors["base"] = "name_exists"
            elif (
                candidate.get(CONF_USE_WORKDAY_SENSOR, True)
                and not candidate.get(CONF_WORKDAY_SENSOR)
            ):
                errors["base"] = "workday_required"
            if not errors:
                self._data[CONF_NAME] = candidate[CONF_NAME]
                self._data[CONF_USE_WORKDAY_SENSOR] = candidate.get(CONF_USE_WORKDAY_SENSOR, True)
                self._data[CONF_WORKDAY_SENSOR] = _sanitize_optional(candidate.get(CONF_WORKDAY_SENSOR))
                self._data[CONF_WORKDAY_SENSOR_TOMORROW] = _sanitize_optional(
                    candidate.get(CONF_WORKDAY_SENSOR_TOMORROW)
                )
                return await self.async_step_shifts()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._data),
            errors=errors,
        )

    async def async_step_shifts(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            duration = int(user_input.get(CONF_SHIFT_DURATION, 0))
            num = int(user_input.get(CONF_NUM_SHIFTS, 0))
            if duration <= 0:
                errors["base"] = "invalid_shift_duration"
            elif num < 1 or num > 9:
                errors["base"] = "invalid_num_shifts"
            if not errors:
                self._data[CONF_SHIFT_DURATION] = duration
                self._data[CONF_NUM_SHIFTS] = num
                return await self.async_step_start_times()

        return self.async_show_form(
            step_id="shifts",
            data_schema=_shift_schema(self._data),
            errors=errors,
        )

    async def async_step_start_times(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            num_shifts = int(self._data.get(CONF_NUM_SHIFTS, 1))
            times: list[str] = []
            for i in range(1, num_shifts + 1):
                value = user_input.get(f"{CONF_START_TIMES}_{i}")
                try:
                    datetime.strptime(value, "%H:%M")
                except (TypeError, ValueError):
                    errors["base"] = "invalid_time_format"
                    break
                times.append(value)
            if not errors and not _start_times_sorted(times):
                errors["base"] = "times_not_sorted"
            if not errors:
                self._data[CONF_START_TIMES] = times
                return await self.async_step_schedule()

        return self.async_show_form(
            step_id="start_times",
            data_schema=_start_times_schema(self._data),
            errors=errors,
        )

    async def async_step_schedule(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            date_str = user_input.get(CONF_SCHEDULE_START)
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                errors["base"] = "invalid_date"
            sched = user_input.get(CONF_SCHEDULE, "")
            if sched and (
                not sched.isdigit()
                or any(int(ch) > self._data.get(CONF_NUM_SHIFTS, 1) for ch in sched)
            ):
                errors["base"] = "invalid_schedule"
            if not errors:
                self._data[CONF_SCHEDULE_START] = date_str
                self._data[CONF_SCHEDULE] = sched
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=self._data[CONF_NAME],
                )
                return self.async_create_entry(title="", data=self._data)

        return self.async_show_form(
            step_id="schedule",
            data_schema=_schedule_schema(self._data),
            errors=errors,
            description_placeholders={"max": self._data.get(CONF_NUM_SHIFTS, 1)},
        )


async def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    return WorkshiftOptionsFlow(config_entry)
