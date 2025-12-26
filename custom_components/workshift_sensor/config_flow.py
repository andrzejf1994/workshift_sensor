from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Any
import re
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
    SOURCE_RECONFIGURE,
)
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_NAME
import homeassistant.helpers.selector as selector

from . import DOMAIN

# Configuration keys
CONF_NAME_PREFIX = "name_prefix"
CONF_WORKDAY_SENSOR = "workday_sensor"
CONF_WORKDAY_SENSOR_TOMORROW = "workday_sensor_tomorrow"
CONF_USE_WORKDAY_SENSOR = "use_workday_sensor"
CONF_SHIFT_DURATION = "shift_duration"
CONF_NUM_SHIFTS = "num_shifts"
CONF_START_TIMES = "start_times"
CONF_SCHEDULE_START = "schedule_start"
CONF_SCHEDULE = "schedule"
CONF_MANUAL_DAYS_OFF = "manual_days_off"
CONF_DAY_OFF_INPUT = "day_off_input"
CONF_REMOVE_DAYS_OFF = "remove_days_off"


def _default_last_monday() -> str:
    today = date.today()
    days_since = today.weekday()
    last_monday = today - timedelta(days=days_since)
    return last_monday.strftime("%Y-%m-%d")


def _parse_day_off(text: str) -> list[dict[str, str]]:
    """Parse single date or range into normalized dicts."""
    parsed: list[dict[str, str]] = []
    if not text:
        return parsed
    parts = [p.strip() for p in re.split(r"[,\n]", text) if p.strip()]
    if not parts:
        return parsed
    for part in parts:
        match_range = re.match(
            r"^(\d{4}-\d{2}-\d{2})\s*(?:-|–|—|to)\s*(\d{4}-\d{2}-\d{2})$", part
        )
        match_single = re.match(r"^(\d{4}-\d{2}-\d{2})$", part)
        if match_range:
            start_str, end_str = match_range.groups()
        elif match_single:
            start_str = end_str = match_single.group(1)
        else:
            raise vol.Invalid("invalid_day_off")

        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
        except Exception as exc:
            raise vol.Invalid("invalid_day_off") from exc

        if end_date < start_date:
            raise vol.Invalid("invalid_day_off")

        parsed.append({"start": start_date.isoformat(), "end": end_date.isoformat()})
    return parsed


def _format_day_off(entry: dict[str, str]) -> str:
    start = entry.get("start")
    end = entry.get("end")
    if start and end and start != end:
        return f"{start} – {end}"
    return start or ""

class WorkshiftConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._reconfigure_entry: ConfigEntry | None = None

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow reconfiguration of an existing entry."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._data = {**self._reconfigure_entry.data, **self._reconfigure_entry.options}
        self.context["title_placeholders"] = {"entry_name": self._reconfigure_entry.title}
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for entry in self._async_current_entries():
                if (
                    self.source == SOURCE_RECONFIGURE
                    and self._reconfigure_entry
                    and entry.entry_id == self._reconfigure_entry.entry_id
                ):
                    continue
                if entry.data.get(CONF_NAME) == user_input[CONF_NAME]:
                    errors["base"] = "name_exists"
                    break
            if not errors:
                self._data.update(user_input)
                return await self.async_step_shifts()

        default_name = self._data.get(CONF_NAME, "")
        default_prefix = self._data.get(CONF_NAME_PREFIX, "")
        default_workday = self._data.get(CONF_WORKDAY_SENSOR, "binary_sensor.workday_sensor")
        default_tomorrow = self._data.get(CONF_WORKDAY_SENSOR_TOMORROW, default_workday)
        default_use_workday = self._data.get(CONF_USE_WORKDAY_SENSOR, True)
        schema = vol.Schema({
            vol.Required(CONF_NAME, default=default_name): selector.TextSelector(),
            vol.Optional(CONF_NAME_PREFIX, default=default_prefix): selector.TextSelector(),
            vol.Required(CONF_USE_WORKDAY_SENSOR, default=default_use_workday): selector.BooleanSelector(),
            vol.Required(CONF_WORKDAY_SENSOR, default=default_workday): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_WORKDAY_SENSOR_TOMORROW, default=default_tomorrow): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_shifts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    async def async_step_start_times(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
                return await self.async_step_days_off()

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

    async def async_step_days_off(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add or remove manual days off (single days or ranges)."""
        errors: dict[str, str] = {}
        current = self._data.get(CONF_MANUAL_DAYS_OFF, [])
        options = [_format_day_off(item) for item in current if _format_day_off(item)]

        schema = vol.Schema({
            vol.Optional(CONF_DAY_OFF_INPUT, default=""): str,
            vol.Optional(CONF_REMOVE_DAYS_OFF, default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        if user_input is not None:
            updated = list(current)
            to_remove = set(user_input.get(CONF_REMOVE_DAYS_OFF, []))
            if to_remove:
                updated = [item for item in updated if _format_day_off(item) not in to_remove]

            day_off_input = user_input.get(CONF_DAY_OFF_INPUT, "").strip()
            if day_off_input:
                try:
                    parsed = _parse_day_off(day_off_input)
                except vol.Invalid:
                    errors["base"] = "invalid_day_off"
                else:
                    updated.extend(parsed)

            if not errors:
                self._data[CONF_MANUAL_DAYS_OFF] = updated
                if self.source == SOURCE_RECONFIGURE and self._reconfigure_entry:
                    options = {
                        **self._reconfigure_entry.options,
                        CONF_MANUAL_DAYS_OFF: self._data.get(CONF_MANUAL_DAYS_OFF, []),
                    }
                    return self.async_update_reload_and_abort(
                        self._reconfigure_entry, data=self._data, options=options
                    )
                return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        return self.async_show_form(
            step_id="days_off",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "examples": "2024-12-24, 2024-12-31 – 2025-01-02",
                "current": "\n".join(options) if options else "-",
            },
        )


class WorkshiftOptionsFlowHandler(OptionsFlowWithReload):
    """Options flow to manage manual days off."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._data = {**entry.data, **entry.options}

    async def async_step_init(self, user_input=None):
        return await self.async_step_days_off()

    async def async_step_days_off(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self._data.get(CONF_MANUAL_DAYS_OFF, [])
        options = [_format_day_off(item) for item in current if _format_day_off(item)]

        schema = vol.Schema({
            vol.Optional(CONF_DAY_OFF_INPUT, default=""): str,
            vol.Optional(CONF_REMOVE_DAYS_OFF, default=[]): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        })

        if user_input is not None:
            updated = list(current)
            to_remove = set(user_input.get(CONF_REMOVE_DAYS_OFF, []))
            if to_remove:
                updated = [item for item in updated if _format_day_off(item) not in to_remove]

            day_off_input = user_input.get(CONF_DAY_OFF_INPUT, "").strip()
            if day_off_input:
                try:
                    parsed = _parse_day_off(day_off_input)
                except vol.Invalid:
                    errors["base"] = "invalid_day_off"
                else:
                    updated.extend(parsed)

            if not errors:
                return self.async_create_entry(title=self._entry.title, data={CONF_MANUAL_DAYS_OFF: updated})

        return self.async_show_form(
            step_id="days_off",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "examples": "2024-12-24, 2024-12-31 – 2025-01-02",
                "current": "\n".join(options) if options else "-",
            },
        )


async def async_get_options_flow(config_entry: ConfigEntry):
    return WorkshiftOptionsFlowHandler(config_entry)
