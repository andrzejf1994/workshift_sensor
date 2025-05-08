from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_NAME
import homeassistant.helpers.selector as selector

from . import DOMAIN

# Configuration keys
CONF_WORKDAY_SENSOR = "workday_sensor"
CONF_WORKDAY_SENSOR_TOMORROW = "workday_sensor_tomorrow"
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

class WorkshiftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            for entry in self._async_current_entries():
                if entry.data.get(CONF_NAME) == user_input[CONF_NAME]:
                    errors["base"] = "name_exists"
                    break
            if not errors:
                self._data.update(user_input)
                return await self.async_step_shifts()

        default_name = self._data.get(CONF_NAME, "")
        default_workday = self._data.get(CONF_WORKDAY_SENSOR, "binary_sensor.workday_sensor")
        default_tomorrow = self._data.get(CONF_WORKDAY_SENSOR_TOMORROW, default_workday)
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=default_name): selector.TextSelector(),
            vol.Required(CONF_WORKDAY_SENSOR, default=default_workday): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_WORKDAY_SENSOR_TOMORROW, default=default_tomorrow): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_shifts(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            num = user_input.get(CONF_NUM_SHIFTS)
            if num is None or num < 1 or num > 9:
                errors["base"] = "invalid_num_shifts"
            if not errors:
                self._data.update(user_input)
                return await self.async_step_start_times()

        schema = vol.Schema({
            vol.Required(CONF_SHIFT_DURATION, default=self._data.get(CONF_SHIFT_DURATION, 8)): vol.Coerce(int),
            vol.Required(CONF_NUM_SHIFTS, default=self._data.get(CONF_NUM_SHIFTS, 3)): vol.Coerce(int),
        })
        return self.async_show_form(step_id="shifts", data_schema=schema, errors=errors)

    async def async_step_start_times(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        num_shifts = self._data.get(CONF_NUM_SHIFTS, 1)
        defaults = self._data.get(CONF_START_TIMES, [])
        schema_fields: dict = {}
        base = datetime.strptime("06:00", "%H:%M")
        duration = self._data.get(CONF_SHIFT_DURATION, 8)
        for i in range(1, num_shifts + 1):
            if i-1 < len(defaults):
                default = defaults[i-1]
            else:
                default = (base + timedelta(hours=duration*(i-1))).strftime("%H:%M")
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
                int(times[i].split(':')[0])*60+int(times[i].split(':')[1]) >=
                int(times[i+1].split(':')[0])*60+int(times[i+1].split(':')[1])
                for i in range(len(times)-1)
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
            if not sched.isdigit() or any(int(ch) > self._data.get(CONF_NUM_SHIFTS,1) for ch in sched):
                errors["base"] = "invalid_schedule"
            if not errors:
                self._data[CONF_SCHEDULE_START] = date_str
                self._data[CONF_SCHEDULE] = sched
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        schema = vol.Schema({
            vol.Required(CONF_SCHEDULE_START, default=self._data.get(CONF_SCHEDULE_START, _default_last_monday())): str,
            vol.Required(CONF_SCHEDULE, default=self._data.get(CONF_SCHEDULE, "")): str,
        })
        return self.async_show_form(
            step_id="schedule",
            data_schema=schema,
            errors=errors,
            description_placeholders={"max": self._data.get(CONF_NUM_SHIFTS,1)}
        )