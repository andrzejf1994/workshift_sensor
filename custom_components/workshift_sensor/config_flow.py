"""Config flow for Workshift Sensor integration."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

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
    DEFAULT_SHIFT_HOURS,
    DEFAULT_SHIFTS_PER_DAY,
    DEFAULT_SCHEDULE_STRING,
    DOMAIN,
)

GENERAL_STEP_ID = "user"
SHIFTS_STEP_ID = "shifts"
SHIFT_TIMES_STEP_ID = "shift_times"
SCHEDULE_STEP_ID = "schedule"

SHIFT_START_KEY_TEMPLATE = "shift_start_{index}"
DEFAULT_ENTRY_NAME = "Workshift"


class WorkshiftFlowHandlerBase:
    """Shared helpers for both config and options flows."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._shift_keys: List[str] = []

    def _merge_defaults(self, user_input: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        combined: Dict[str, Any] = {**self._data}
        if user_input:
            combined.update(user_input)
        return combined

    def _general_schema(self, user_input: Optional[Mapping[str, Any]]) -> vol.Schema:
        data = self._merge_defaults(user_input)
        use_workday = bool(data.get(CONF_USE_WORKDAY_SENSOR, False))
        schema_dict: Dict[Any, Any] = {
            vol.Required(
                CONF_ENTRY_NAME,
                default=data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME),
            ): selector.selector({"text": {"multiline": False}}),
            vol.Required(
                CONF_USE_WORKDAY_SENSOR,
                default=use_workday,
            ): selector.selector({"boolean": {}}),
        }
        if use_workday:
            schema_dict.update(
                {
                    vol.Required(
                        CONF_WORKDAY_ENTITY_TODAY,
                        default=data.get(CONF_WORKDAY_ENTITY_TODAY)
                        or "binary_sensor.workday_sensor",
                    ): selector.selector(
                        {"entity": {"domain": "binary_sensor"}}
                    ),
                    vol.Optional(
                        CONF_WORKDAY_ENTITY_TOMORROW,
                        default=data.get(CONF_WORKDAY_ENTITY_TOMORROW, "") or "",
                    ): selector.selector(
                        {"entity": {"domain": "binary_sensor"}}
                    ),
                }
            )
        return vol.Schema(schema_dict)

    def _shifts_schema(self, user_input: Optional[Mapping[str, Any]]) -> vol.Schema:
        data = self._merge_defaults(user_input)
        return vol.Schema(
            {
                vol.Required(
                    CONF_SHIFT_HOURS,
                    default=int(data.get(CONF_SHIFT_HOURS, DEFAULT_SHIFT_HOURS)),
                ): selector.selector(
                    {
                        "number": {
                            "min": 1,
                            "max": 24,
                            "mode": "box",
                            "step": 1,
                        }
                    }
                ),
                vol.Required(
                    CONF_SHIFTS_PER_DAY,
                    default=int(data.get(CONF_SHIFTS_PER_DAY, DEFAULT_SHIFTS_PER_DAY)),
                ): selector.selector(
                    {
                        "number": {
                            "min": 1,
                            "max": 9,
                            "mode": "box",
                            "step": 1,
                        }
                    }
                ),
            }
        )

    def _shift_times_schema(self, user_input: Optional[Mapping[str, Any]]) -> vol.Schema:
        shifts_per_day = int(self._data[CONF_SHIFTS_PER_DAY])
        defaults = self._default_shift_starts()
        schema_dict: Dict[Any, Any] = {}
        self._shift_keys = []
        for index in range(shifts_per_day):
            key = SHIFT_START_KEY_TEMPLATE.format(index=index)
            self._shift_keys.append(key)
            default_value = defaults[index]
            if user_input and key in user_input:
                default_value = user_input[key]
            schema_dict[vol.Required(key, default=default_value)] = selector.selector(
                {"time": {}}
            )
        return vol.Schema(schema_dict)

    def _schedule_schema(self, user_input: Optional[Mapping[str, Any]]) -> vol.Schema:
        data = self._merge_defaults(user_input)
        start_default = data.get(CONF_SCHEDULE_START_DATE, self._default_schedule_start())
        schedule_default = data.get(CONF_SCHEDULE_STRING, DEFAULT_SCHEDULE_STRING)
        return vol.Schema(
            {
                vol.Required(
                    CONF_SCHEDULE_START_DATE,
                    default=start_default,
                ): selector.selector({"date": {}}),
                vol.Required(
                    CONF_SCHEDULE_STRING,
                    default=schedule_default,
                ): selector.selector({"text": {"multiline": False}}),
            }
        )

    def _default_shift_starts(self) -> List[str]:
        shifts_per_day = int(self._data.get(CONF_SHIFTS_PER_DAY, DEFAULT_SHIFTS_PER_DAY))
        existing = self._data.get(CONF_SHIFT_STARTS)
        if isinstance(existing, list) and len(existing) == shifts_per_day:
            return [str(value) for value in existing]

        base_time_str = "06:00"
        if existing:
            base_time_str = str(existing[0])

        try:
            base_time = datetime.strptime(base_time_str, "%H:%M")
        except ValueError:
            base_time = datetime.strptime("06:00", "%H:%M")

        shift_hours = int(self._data.get(CONF_SHIFT_HOURS, DEFAULT_SHIFT_HOURS))
        values: List[str] = []
        for index in range(shifts_per_day):
            current = base_time + timedelta(hours=shift_hours * index)
            values.append(current.time().strftime("%H:%M"))
        return values

    def _default_schedule_start(self) -> str:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def _clean_general(self, user_input: Mapping[str, Any]) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            CONF_ENTRY_NAME: str(user_input[CONF_ENTRY_NAME]).strip() or DEFAULT_ENTRY_NAME,
            CONF_USE_WORKDAY_SENSOR: bool(user_input[CONF_USE_WORKDAY_SENSOR]),
            CONF_WORKDAY_ENTITY_TODAY: None,
            CONF_WORKDAY_ENTITY_TOMORROW: None,
        }
        if data[CONF_USE_WORKDAY_SENSOR]:
            today_entity = user_input.get(CONF_WORKDAY_ENTITY_TODAY)
            if today_entity:
                data[CONF_WORKDAY_ENTITY_TODAY] = today_entity
            tomorrow = user_input.get(CONF_WORKDAY_ENTITY_TOMORROW)
            if tomorrow:
                data[CONF_WORKDAY_ENTITY_TOMORROW] = tomorrow
        return data

    def _clean_shift_core(self, user_input: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            CONF_SHIFT_HOURS: int(user_input[CONF_SHIFT_HOURS]),
            CONF_SHIFTS_PER_DAY: int(user_input[CONF_SHIFTS_PER_DAY]),
        }

    def _clean_shift_times(self, user_input: Mapping[str, Any]) -> Dict[str, Any]:
        start_values = [str(user_input[key]) for key in self._shift_keys]
        validated = _validate_shift_starts(start_values)
        return {CONF_SHIFT_STARTS: validated}

    def _clean_schedule(self, user_input: Mapping[str, Any]) -> Dict[str, Any]:
        start_date = str(user_input[CONF_SCHEDULE_START_DATE])
        schedule = str(user_input[CONF_SCHEDULE_STRING]).strip().replace(" ", "")
        return {
            CONF_SCHEDULE_START_DATE: start_date,
            CONF_SCHEDULE_STRING: schedule,
        }

    def _finalize(self) -> Dict[str, Any]:
        result = dict(self._data)
        if not result.get(CONF_USE_WORKDAY_SENSOR, False):
            result.pop(CONF_WORKDAY_ENTITY_TODAY, None)
            result.pop(CONF_WORKDAY_ENTITY_TOMORROW, None)
        else:
            if not result.get(CONF_WORKDAY_ENTITY_TOMORROW):
                result.pop(CONF_WORKDAY_ENTITY_TOMORROW, None)
        return result


class WorkshiftConfigFlow(WorkshiftFlowHandlerBase, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Workshift Sensor."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            cleaned = self._clean_general(user_input)
            if cleaned[CONF_USE_WORKDAY_SENSOR] and not cleaned.get(CONF_WORKDAY_ENTITY_TODAY):
                errors[CONF_WORKDAY_ENTITY_TODAY] = "workday_required"
            else:
                self._data.update(cleaned)
                return await self.async_step_shifts()

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=GENERAL_STEP_ID,
            data_schema=self._general_schema(user_input),
            errors=errors,
        )

    async def async_step_shifts(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            cleaned = self._clean_shift_core(user_input)
            shift_hours = cleaned[CONF_SHIFT_HOURS]
            shifts_per_day = cleaned[CONF_SHIFTS_PER_DAY]
            if not 1 <= shift_hours <= 24:
                errors[CONF_SHIFT_HOURS] = "invalid_shift_hours"
            elif not 1 <= shifts_per_day <= 9:
                errors[CONF_SHIFTS_PER_DAY] = "invalid_shifts_per_day"
            else:
                self._data.update(cleaned)
                return await self.async_step_shift_times()

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=SHIFTS_STEP_ID,
            data_schema=self._shifts_schema(user_input),
            errors=errors,
        )

    async def async_step_shift_times(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                cleaned = self._clean_shift_times(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._data.update(cleaned)
                return await self.async_step_schedule()

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=SHIFT_TIMES_STEP_ID,
            data_schema=self._shift_times_schema(user_input),
            errors=errors,
        )

    async def async_step_schedule(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            cleaned = self._clean_schedule(user_input)
            try:
                _validate_schedule(
                    cleaned[CONF_SCHEDULE_START_DATE],
                    cleaned[CONF_SCHEDULE_STRING],
                    int(self._data[CONF_SHIFTS_PER_DAY]),
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._data.update(cleaned)
                final_data = self._finalize()
                title = final_data[CONF_ENTRY_NAME]
                return self.async_create_entry(title=title, data=final_data)

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=SCHEDULE_STEP_ID,
            data_schema=self._schedule_schema(user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return WorkshiftOptionsFlow(config_entry)


class WorkshiftOptionsFlow(WorkshiftFlowHandlerBase, config_entries.OptionsFlow):
    """Options flow allowing to reconfigure the integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry
        self._data.update({**config_entry.data, **config_entry.options})

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None):
        return await self.async_step_user(user_input)

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            cleaned = self._clean_general(user_input)
            if cleaned[CONF_USE_WORKDAY_SENSOR] and not cleaned.get(CONF_WORKDAY_ENTITY_TODAY):
                errors[CONF_WORKDAY_ENTITY_TODAY] = "workday_required"
            else:
                self._data.update(cleaned)
                return await self.async_step_shifts()

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=GENERAL_STEP_ID,
            data_schema=self._general_schema(user_input),
            errors=errors,
        )

    async def async_step_shifts(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            cleaned = self._clean_shift_core(user_input)
            shift_hours = cleaned[CONF_SHIFT_HOURS]
            shifts_per_day = cleaned[CONF_SHIFTS_PER_DAY]
            if not 1 <= shift_hours <= 24:
                errors[CONF_SHIFT_HOURS] = "invalid_shift_hours"
            elif not 1 <= shifts_per_day <= 9:
                errors[CONF_SHIFTS_PER_DAY] = "invalid_shifts_per_day"
            else:
                self._data.update(cleaned)
                return await self.async_step_shift_times()

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=SHIFTS_STEP_ID,
            data_schema=self._shifts_schema(user_input),
            errors=errors,
        )

    async def async_step_shift_times(
        self, user_input: Optional[Dict[str, Any]] = None
    ):
        errors: Dict[str, str] = {}
        if user_input is not None:
            try:
                cleaned = self._clean_shift_times(user_input)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._data.update(cleaned)
                return await self.async_step_schedule()

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=SHIFT_TIMES_STEP_ID,
            data_schema=self._shift_times_schema(user_input),
            errors=errors,
        )

    async def async_step_schedule(self, user_input: Optional[Dict[str, Any]] = None):
        errors: Dict[str, str] = {}
        if user_input is not None:
            cleaned = self._clean_schedule(user_input)
            try:
                _validate_schedule(
                    cleaned[CONF_SCHEDULE_START_DATE],
                    cleaned[CONF_SCHEDULE_STRING],
                    int(self._data[CONF_SHIFTS_PER_DAY]),
                )
            except ValueError as err:
                errors["base"] = str(err)
            else:
                self._data.update(cleaned)
                final_data = self._finalize()
                return self.async_create_entry(title="", data=final_data)

        self.context["title_placeholders"] = {
            "entry_name": self._data.get(CONF_ENTRY_NAME, DEFAULT_ENTRY_NAME)
        }

        return self.async_show_form(
            step_id=SCHEDULE_STEP_ID,
            data_schema=self._schedule_schema(user_input),
            errors=errors,
        )


def _validate_shift_starts(values: List[str]) -> List[str]:
    """Validate shift start times and return normalized list."""

    last_minutes: Optional[int] = None
    normalized: List[str] = []
    for value in values:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError as err:
            raise ValueError("invalid_shift_start_format") from err
        minutes = parsed.hour * 60 + parsed.minute
        if last_minutes is not None and minutes <= last_minutes:
            raise ValueError("invalid_shift_start_order")
        last_minutes = minutes
        normalized.append(parsed.time().strftime("%H:%M"))
    return normalized


def _validate_schedule(start_date: str, schedule: str, shifts_per_day: int) -> None:
    """Validate schedule string and start date."""

    try:
        date.fromisoformat(start_date)
    except ValueError as err:
        raise ValueError("invalid_schedule_date") from err

    if not schedule:
        raise ValueError("invalid_schedule_pattern")
    if not schedule.isdigit():
        raise ValueError("invalid_schedule_pattern")
    if any(int(ch) > shifts_per_day for ch in schedule):
        raise ValueError("invalid_schedule_digit")
