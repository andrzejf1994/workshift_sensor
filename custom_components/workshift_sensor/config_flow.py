from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_NAME
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


def _time_to_minutes(value: str) -> int:
    """Convert HH:MM string to minutes after midnight."""
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


class WorkshiftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        entry = self._get_reconfigure_entry()
        if not self._data:
            self._data = dict(entry.data)
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            current_entry_id = None
            if self.source == SOURCE_RECONFIGURE:
                current_entry_id = self._get_reconfigure_entry().entry_id
            for entry in self._async_current_entries():
                if entry.data.get(CONF_NAME) == user_input[CONF_NAME] and entry.entry_id != current_entry_id:
                    errors["base"] = "name_exists"
                    break

            if not errors:
                self._data[CONF_NAME] = user_input[CONF_NAME]
                use_workday = user_input[CONF_USE_WORKDAY_SENSOR]
                self._data[CONF_USE_WORKDAY_SENSOR] = use_workday

                if not use_workday:
                    self._data.pop(CONF_WORKDAY_SENSOR, None)
                    self._data.pop(CONF_WORKDAY_SENSOR_TOMORROW, None)
                    return await self.async_step_shifts()

                return await self.async_step_workday()

        default_name = self._data.get(CONF_NAME, "")
        default_use_workday = self._data.get(CONF_USE_WORKDAY_SENSOR, True)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=default_name): selector.TextSelector(),
                vol.Required(CONF_USE_WORKDAY_SENSOR, default=default_use_workday): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_workday(self, user_input: dict[str, Any] | None = None):
        if not self._data.get(CONF_USE_WORKDAY_SENSOR, True):
            return await self.async_step_shifts()

        errors: dict[str, str] = {}

        default_workday = self._data.get(CONF_WORKDAY_SENSOR, "binary_sensor.workday_sensor")
        default_tomorrow = self._data.get(CONF_WORKDAY_SENSOR_TOMORROW, default_workday)

        schema = vol.Schema(
            {
                vol.Required(CONF_WORKDAY_SENSOR, default=default_workday): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
                vol.Optional(CONF_WORKDAY_SENSOR_TOMORROW, default=default_tomorrow): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="binary_sensor")
                ),
            }
        )

        if user_input is not None:
            workday_sensor = user_input.get(CONF_WORKDAY_SENSOR)
            if not workday_sensor:
                errors[CONF_WORKDAY_SENSOR] = "workday_sensor_required"
            else:
                self._data[CONF_WORKDAY_SENSOR] = workday_sensor

                workday_tomorrow = user_input.get(CONF_WORKDAY_SENSOR_TOMORROW)
                if workday_tomorrow:
                    self._data[CONF_WORKDAY_SENSOR_TOMORROW] = workday_tomorrow
                else:
                    self._data.pop(CONF_WORKDAY_SENSOR_TOMORROW, None)

                return await self.async_step_shifts()

        return self.async_show_form(step_id="workday", data_schema=schema, errors=errors)

    async def async_step_shifts(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            num = user_input.get(CONF_NUM_SHIFTS)
            if num is None or num < 1 or num > 9:
                errors["base"] = "invalid_num_shifts"
            if not errors:
                self._data.update(user_input)
                return await self.async_step_start_times()

        schema = vol.Schema(
            {
                vol.Required(CONF_SHIFT_DURATION, default=self._data.get(CONF_SHIFT_DURATION, 8)): vol.Coerce(int),
                vol.Required(CONF_NUM_SHIFTS, default=self._data.get(CONF_NUM_SHIFTS, 3)): vol.Coerce(int),
            }
        )
        return self.async_show_form(step_id="shifts", data_schema=schema, errors=errors)

    async def async_step_start_times(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        num_shifts = self._data.get(CONF_NUM_SHIFTS, 1)
        defaults = self._data.get(CONF_START_TIMES, [])
        schema_fields: dict[Any, Any] = {}
        base = datetime.strptime("06:00", "%H:%M")
        duration = self._data.get(CONF_SHIFT_DURATION, 8)
        for i in range(1, num_shifts + 1):
            if i - 1 < len(defaults):
                default = defaults[i - 1]
            else:
                default = (base + timedelta(hours=duration * (i - 1))).strftime("%H:%M")
            schema_fields[vol.Required(f"{CONF_START_TIMES}_{i}", default=default)] = str
        schema = vol.Schema(schema_fields)

        if user_input is not None:
            times: list[str] = []
            for i in range(1, num_shifts + 1):
                t = user_input.get(f"{CONF_START_TIMES}_{i}")
                try:
                    datetime.strptime(t, "%H:%M")
                except Exception:
                    errors["base"] = "invalid_time_format"
                times.append(t)
            if not errors and any(
                _time_to_minutes(times[i]) >= _time_to_minutes(times[i + 1])
                for i in range(len(times) - 1)
            ):
                errors["base"] = "times_not_sorted"
            if not errors:
                self._data[CONF_START_TIMES] = times
                return await self.async_step_schedule()

        return self.async_show_form(step_id="start_times", data_schema=schema, errors=errors)

    async def async_step_schedule(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            date_str = user_input.get(CONF_SCHEDULE_START)
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except Exception:
                errors["base"] = "invalid_date"
            sched = user_input.get(CONF_SCHEDULE, "")
            if not sched.isdigit() or any(int(ch) > self._data.get(CONF_NUM_SHIFTS, 1) for ch in sched):
                errors["base"] = "invalid_schedule"
            if not errors:
                self._data[CONF_SCHEDULE_START] = date_str
                self._data[CONF_SCHEDULE] = sched
                if self.source == SOURCE_RECONFIGURE:
                    entry = self._get_reconfigure_entry()
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=self._data,
                        title=self._data[CONF_NAME],
                    )
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCHEDULE_START,
                    default=self._data.get(CONF_SCHEDULE_START, _default_last_monday()),
                ): str,
                vol.Required(CONF_SCHEDULE, default=self._data.get(CONF_SCHEDULE, "")): str,
            }
        )
        return self.async_show_form(
            step_id="schedule",
            data_schema=schema,
            errors=errors,
            description_placeholders={"max": self._data.get(CONF_NUM_SHIFTS, 1)},
        )
