"""Config flow for the Workshift Sensor integration."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.selector as selector

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
    DEFAULT_WORKDAY_SENSOR,
    DOMAIN,
    MAX_SHIFTS,
)
from .util import WorkshiftConfigData


def _default_last_monday() -> str:
    today = date.today()
    days_since = today.weekday()
    last_monday = today - timedelta(days=days_since)
    return last_monday.strftime("%Y-%m-%d")


def _sanitize_optional(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = value.strip()
    else:
        candidate = str(value).strip()
    return candidate or None


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "on", "1", "yes"}:
            return True
        if lowered in {"false", "off", "0", "no"}:
            return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _start_times_sorted(times: list[str]) -> bool:
    minutes: list[int] = []
    for value in times:
        hour, minute = value.split(":")
        minutes.append(int(hour) * 60 + int(minute))
    return all(curr > prev for prev, curr in zip(minutes, minutes[1:]))


def _name_in_use(
    hass: HomeAssistant, name: str, *, exclude_entry_id: str | None = None
) -> bool:
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


def _user_schema(config: WorkshiftConfigData) -> vol.Schema:
    default_workday = config.workday_sensor or DEFAULT_WORKDAY_SENSOR
    default_tomorrow = config.workday_sensor_tomorrow or default_workday
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=config.name): selector.TextSelector(),
            vol.Required(
                CONF_USE_WORKDAY_SENSOR, default=config.use_workday_sensor
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_WORKDAY_SENSOR, default=default_workday
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(
                CONF_WORKDAY_SENSOR_TOMORROW, default=default_tomorrow
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
        }
    )


def _shift_schema(config: WorkshiftConfigData) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SHIFT_DURATION,
                default=config.shift_duration or DEFAULT_SHIFT_DURATION,
            ): vol.Coerce(int),
            vol.Required(
                CONF_NUM_SHIFTS,
                default=config.num_shifts or DEFAULT_NUM_SHIFTS,
            ): vol.Coerce(int),
        }
    )


def _start_times_schema(config: WorkshiftConfigData) -> vol.Schema:
    defaults = list(config.ensure_start_times().start_times)
    fields: dict[Any, Any] = {}
    for index in range(1, config.num_shifts + 1):
        default = defaults[index - 1] if index - 1 < len(defaults) else "06:00"
        fields[vol.Required(f"{CONF_START_TIMES}_{index}", default=default)] = str
    return vol.Schema(fields)


def _schedule_schema(config: WorkshiftConfigData) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_SCHEDULE_START,
                default=config.schedule_start or _default_last_monday(),
            ): str,
            vol.Required(CONF_SCHEDULE, default=config.schedule): str,
        }
    )


def _process_general_step(
    hass: HomeAssistant,
    config: WorkshiftConfigData,
    user_input: dict[str, Any],
    *,
    exclude_entry_id: str | None,
) -> tuple[WorkshiftConfigData, dict[str, str]]:
    errors: dict[str, str] = {}
    name = str(user_input.get(CONF_NAME, config.name)).strip()
    use_workday = _coerce_bool(
        user_input.get(CONF_USE_WORKDAY_SENSOR, config.use_workday_sensor),
        config.use_workday_sensor,
    )
    workday_sensor = _sanitize_optional(user_input.get(CONF_WORKDAY_SENSOR))
    workday_tomorrow = _sanitize_optional(
        user_input.get(CONF_WORKDAY_SENSOR_TOMORROW)
    )

    if not name:
        errors["base"] = "invalid_name"
    elif _name_in_use(hass, name, exclude_entry_id=exclude_entry_id):
        errors["base"] = "name_exists"
    elif use_workday and not workday_sensor:
        errors["base"] = "workday_required"

    if errors:
        return config, errors

    if not use_workday:
        workday_sensor = None
        workday_tomorrow = None
    elif workday_tomorrow is None:
        workday_tomorrow = workday_sensor

    updated = config.with_updates(
        name=name,
        use_workday_sensor=use_workday,
        workday_sensor=workday_sensor,
        workday_sensor_tomorrow=workday_tomorrow,
    )
    return updated, errors


def _process_shifts_step(
    config: WorkshiftConfigData, user_input: dict[str, Any]
) -> tuple[WorkshiftConfigData, dict[str, str]]:
    errors: dict[str, str] = {}
    duration = _coerce_int(
        user_input.get(CONF_SHIFT_DURATION, config.shift_duration),
        config.shift_duration or DEFAULT_SHIFT_DURATION,
    )
    num_shifts = _coerce_int(
        user_input.get(CONF_NUM_SHIFTS, config.num_shifts),
        config.num_shifts or DEFAULT_NUM_SHIFTS,
    )

    if duration <= 0:
        errors["base"] = "invalid_shift_duration"
    elif num_shifts < 1 or num_shifts > MAX_SHIFTS:
        errors["base"] = "invalid_num_shifts"

    if errors:
        return config, errors

    updated = config.with_updates(
        shift_duration=duration,
        num_shifts=num_shifts,
    )
    return updated, errors


def _process_start_times_step(
    config: WorkshiftConfigData, user_input: dict[str, Any]
) -> tuple[WorkshiftConfigData, dict[str, str]]:
    errors: dict[str, str] = {}
    times: list[str] = []
    for index in range(1, config.num_shifts + 1):
        value = str(user_input.get(f"{CONF_START_TIMES}_{index}", "")).strip()
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            errors["base"] = "invalid_time_format"
            break
        times.append(value)

    if not errors and not _start_times_sorted(times):
        errors["base"] = "times_not_sorted"

    if errors:
        return config, errors

    updated = config.with_updates(start_times=tuple(times))
    return updated, errors


def _process_schedule_step(
    config: WorkshiftConfigData, user_input: dict[str, Any]
) -> tuple[WorkshiftConfigData, dict[str, str]]:
    errors: dict[str, str] = {}
    date_str = str(user_input.get(CONF_SCHEDULE_START, "")).strip()
    schedule = str(user_input.get(CONF_SCHEDULE, "")).strip()

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        errors["base"] = "invalid_date"

    if schedule:
        if not schedule.isdigit() or any(int(ch) > config.num_shifts for ch in schedule):
            errors["base"] = "invalid_schedule"

    if errors:
        return config, errors

    updated = config.with_updates(
        schedule_start=date_str,
        schedule=schedule,
    )
    return updated, errors


class WorkshiftConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the Workshift Sensor integration."""

    VERSION = 1

    def __init__(self) -> None:
        self._config = WorkshiftConfigData()
        self._reconfigure_entry_id: str | None = None
        self._reconfigure_loaded = False

    def _initialize_from_entry(self) -> None:
        if self._reconfigure_loaded or self._reconfigure_entry_id is None:
            return
        entry = self.hass.config_entries.async_get_entry(self._reconfigure_entry_id)
        if entry is None:
            return
        fallback = (
            entry.options.get(CONF_NAME)
            or entry.data.get(CONF_NAME)
            or entry.title
            or DEFAULT_NAME
        )
        merged = {**entry.data, **entry.options}
        self._config = WorkshiftConfigData.from_mapping(merged, fallback_name=fallback)
        self._reconfigure_loaded = True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            exclude_id = self._reconfigure_entry_id
            self._config, errors = _process_general_step(
                self.hass,
                self._config,
                user_input,
                exclude_entry_id=exclude_id,
            )
            if not errors:
                return await self.async_step_shifts()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._config),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if self._reconfigure_entry_id is None:
            entry_id = self.context.get("entry_id")
            if entry_id is None:
                return self.async_abort(reason="unknown_entry")
            self._reconfigure_entry_id = entry_id

        self._initialize_from_entry()

        if not self._reconfigure_loaded:
            return self.async_abort(reason="unknown_entry")

        return await self.async_step_user(user_input)

    async def async_step_shifts(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_shifts_step(self._config, user_input)
            if not errors:
                return await self.async_step_start_times()

        return self.async_show_form(
            step_id="shifts",
            data_schema=_shift_schema(self._config),
            errors=errors,
        )

    async def async_step_start_times(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_start_times_step(self._config, user_input)
            if not errors:
                return await self.async_step_schedule()

        return self.async_show_form(
            step_id="start_times",
            data_schema=_start_times_schema(self._config),
            errors=errors,
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_schedule_step(self._config, user_input)
            if not errors:
                final_config = self._config.ensure_start_times()
                self._config = final_config
                return self.async_create_entry(
                    title=self._config.name,
                    data=self._config.as_dict(),
                )

        return self.async_show_form(
            step_id="schedule",
            data_schema=_schedule_schema(self._config),
            errors=errors,
            description_placeholders={
                "max": str(self._config.num_shifts),
            },
        )


class WorkshiftOptionsFlow(config_entries.OptionsFlow):
    """Handle the options flow for an existing config entry."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        merged = {**config_entry.data, **config_entry.options}
        fallback = (
            config_entry.options.get(CONF_NAME)
            or config_entry.data.get(CONF_NAME)
            or config_entry.title
            or DEFAULT_NAME
        )
        self._config = WorkshiftConfigData.from_mapping(merged, fallback_name=fallback)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return await self.async_step_user(user_input)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_general_step(
                self.hass,
                self._config,
                user_input,
                exclude_entry_id=self.config_entry.entry_id,
            )
            if not errors:
                return await self.async_step_shifts()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(self._config),
            errors=errors,
        )

    async def async_step_shifts(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_shifts_step(self._config, user_input)
            if not errors:
                return await self.async_step_start_times()

        return self.async_show_form(
            step_id="shifts",
            data_schema=_shift_schema(self._config),
            errors=errors,
        )

    async def async_step_start_times(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_start_times_step(self._config, user_input)
            if not errors:
                return await self.async_step_schedule()

        return self.async_show_form(
            step_id="start_times",
            data_schema=_start_times_schema(self._config),
            errors=errors,
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._config, errors = _process_schedule_step(self._config, user_input)
            if not errors:
                final_config = self._config.ensure_start_times()
                self._config = final_config
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=self._config.name,
                )
                return self.async_create_entry(
                    title="",
                    data=self._config.as_dict(),
                )

        return self.async_show_form(
            step_id="schedule",
            data_schema=_schedule_schema(self._config),
            errors=errors,
            description_placeholders={
                "max": str(self._config.num_shifts),
            },
        )


def async_get_options_flow(config_entry: config_entries.ConfigEntry):
    return WorkshiftOptionsFlow(config_entry)
