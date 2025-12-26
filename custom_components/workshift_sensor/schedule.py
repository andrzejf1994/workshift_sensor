from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import logging
from importlib import resources
from typing import Any, Optional
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


def _load_shift_label(lang: str) -> str | None:
    """Blocking translation loader executed in the executor."""
    try:
        with resources.files(__package__).joinpath(
            "translations", f"{lang}.json"
        ).open("r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("shift_label")) if data.get("shift_label") else None
    except FileNotFoundError:
        return None
    except Exception as err:
        _LOGGER.debug("Failed to load shift label for %s: %s", lang, err)
        return None


async def async_get_default_shift_label(hass: HomeAssistant) -> str:
    """Load the localized default shift label without blocking the event loop."""
    language = (hass.config.language or "en").split("-")[0]
    label = await hass.async_add_executor_job(_load_shift_label, language)
    if not label and language != "en":
        label = await hass.async_add_executor_job(_load_shift_label, "en")
    return label or "Shift"


@dataclass
class ShiftInstance:
    """Computed shift details for a specific date."""

    code: int
    start: datetime
    end: datetime
    rotation_index: Optional[int]


class WorkshiftSchedule:
    """Shared schedule logic for workshift entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        default_shift_label: str | None = None,
    ) -> None:
        self.hass = hass
        self._config = config
        
        # FIX #4: Timezone validation using zoneinfo
        self.tz = self._get_validated_timezone()
        
        self.shift_duration = int(self._config.get("shift_duration", 8))
        self._pattern = str(self._config.get("schedule", ""))
        self._start_times = [
            datetime.strptime(t, "%H:%M").time()
            for t in self._config.get("start_times", [])
        ]
        
        # FIX #4: Error handling for date parsing
        try:
            self._base_date = datetime.strptime(
                self._config.get("schedule_start"), "%Y-%m-%d"
            ).date()
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Invalid schedule_start date, using today: %s", err
            )
            self._base_date = dt_util.now(self.tz).date()
        
        self._manual_days_off = self._parse_manual_days_off(
            self._config.get("manual_days_off", [])
        )
        self._use_workday_sensor = self._config.get("use_workday_sensor", True)
        self._workday_today = self._config.get("workday_sensor")
        self._workday_tomorrow = (
            self._config.get("workday_sensor_tomorrow") or self._workday_today
        )
        self._shift_names = self._config.get("shift_names") or []
        self._default_shift_label = (
            default_shift_label
            or self._config.get("default_shift_label")
            or "Shift"
        )

    def _get_validated_timezone(self) -> ZoneInfo:
        """Get and validate the timezone configuration."""
        tz_str = self.hass.config.time_zone
        try:
            return ZoneInfo(tz_str)
        except Exception as err:
            _LOGGER.warning(
                "Invalid timezone '%s', falling back to UTC: %s", 
                tz_str, 
                err
            )
            return ZoneInfo("UTC")

    def shift_name(self, code: int) -> str:
        """Return a friendly shift name for the given code."""
        idx = code - 1
        if 0 <= idx < len(self._shift_names):
            return str(self._shift_names[idx])
        return f"{self._default_shift_label} {code}"

    def get_shift(self, day: date) -> Optional[ShiftInstance]:
        """Return a computed shift for the given day, if any."""
        code, rotation_index = self._get_schedule_code(day)
        if code == 0:
            return None
        idx = code - 1
        if idx < 0 or idx >= len(self._start_times):
            _LOGGER.warning(
                "Shift code %s has no matching start time configured", code
            )
            return None
        start_dt = datetime.combine(day, self._start_times[idx], self.tz)
        end_dt = start_dt + timedelta(hours=self.shift_duration)
        return ShiftInstance(code=code, start=start_dt, end=end_dt, rotation_index=rotation_index)

    def shift_covering(self, moment: datetime) -> Optional[ShiftInstance]:
        """Return a shift that covers the provided moment."""
        localized = self._ensure_local(moment)
        day = localized.date()
        today_shift = self.get_shift(day)
        if today_shift and today_shift.start <= localized < today_shift.end:
            return today_shift
        yesterday_shift = self.get_shift(day - timedelta(days=1))
        if yesterday_shift and yesterday_shift.start <= localized < yesterday_shift.end:
            return yesterday_shift
        return None

    def next_shift_after(self, moment: datetime, search_days: int = 90) -> Optional[ShiftInstance]:
        """Return the first shift that ends after the given moment."""
        localized = self._ensure_local(moment)
        start_day = localized.date()
        for offset in range(search_days):
            target = start_day + timedelta(days=offset)
            shift = self.get_shift(target)
            if shift and shift.end > localized:
                return shift
        return None

    def _get_schedule_code(self, day: date) -> tuple[int, Optional[int]]:
        """Get the shift code for a specific date with all overrides applied."""
        if self._is_manual_day_off(day):
            return 0, None
        if not self._pattern:
            return 0, None
        diff = (day - self._base_date).days
        if diff < 0:
            return 0, None
        try:
            idx = diff % len(self._pattern)
            code = int(self._pattern[idx])
        except (ValueError, IndexError):
            _LOGGER.warning("Invalid schedule pattern value for %s", day)
            return 0, None

        if not self._workday_allowed(day):
            return 0, idx
        return code, idx

    def _workday_allowed(self, day: date) -> bool:
        """Check workday sensor states for the given day, if enabled."""
        if not self._use_workday_sensor:
            return True
        today = dt_util.now(self.tz).date()
        entity_id: Optional[str] = None
        if day == today:
            entity_id = self._workday_today
        elif day == today + timedelta(days=1):
            entity_id = self._workday_tomorrow
        if not entity_id:
            return True
        state = self.hass.states.get(entity_id)
        if state is None:
            return True
        return state.state.lower() != "off"

    def _parse_manual_days_off(self, entries: list[dict]) -> list[tuple[date, date]]:
        """Normalize manual days off to date ranges."""
        ranges: list[tuple[date, date]] = []
        for entry in entries:
            start = entry.get("start")
            end = entry.get("end", start)
            try:
                start_date = datetime.strptime(start, "%Y-%m-%d").date()
                end_date = datetime.strptime(end, "%Y-%m-%d").date()
            except (ValueError, TypeError) as err:
                _LOGGER.warning("Invalid manual day off entry skipped: %s - %s", entry, err)
                continue
            if end_date < start_date:
                start_date, end_date = end_date, start_date
            ranges.append((start_date, end_date))
        return ranges

    def _is_manual_day_off(self, day: date) -> bool:
        """Check if date is marked as a manual day off."""
        return any(start <= day <= end for start, end in self._manual_days_off)

    def _ensure_local(self, moment: datetime) -> datetime:
        """Return a timezone-aware datetime in the integration timezone."""
        if moment.tzinfo is None:
            return moment.replace(tzinfo=self.tz)
        return moment.astimezone(self.tz)

    @callback
    def async_update_timezone(self) -> None:
        """Refresh timezone if Home Assistant time zone changes."""
        self.tz = self._get_validated_timezone()
