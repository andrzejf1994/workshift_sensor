"""Tests for schedule calculations."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from unittest.mock import AsyncMock, Mock, patch

from custom_components.workshift_sensor.schedule import (
    WorkshiftSchedule,
    ShiftInstance,
    async_get_default_shift_label,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = Mock()
    hass.config.time_zone = "Europe/Warsaw"
    hass.config.language = "pl"
    hass.states.get = Mock(return_value=None)
    return hass


@pytest.fixture
def basic_config():
    """Basic configuration for testing."""
    return {
        "shift_duration": 8,
        "schedule": "123012301230",
        "schedule_start": "2025-01-06",  # Monday
        "start_times": ["06:00", "14:00", "22:00"],
        "manual_days_off": [],
        "use_workday_sensor": False,
        "default_shift_label": "Zmiana",
    }


class TestWorkshiftSchedule:
    """Test suite for WorkshiftSchedule class."""

    def test_initialization(self, mock_hass, basic_config):
        """Test basic initialization."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        assert schedule.shift_duration == 8
        assert schedule._pattern == "123012301230"
        assert len(schedule._start_times) == 3
        assert schedule.tz == ZoneInfo("Europe/Warsaw")

    def test_get_shift_basic(self, mock_hass, basic_config):
        """Test basic shift calculation for a working day."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # 2025-01-06 is Monday (offset 0, pattern[0] = '1')
        shift = schedule.get_shift(date(2025, 1, 6))
        
        assert shift is not None
        assert shift.code == 1
        assert shift.start.hour == 6
        assert shift.start.minute == 0
        assert shift.end == shift.start + timedelta(hours=8)

    def test_get_shift_day_off(self, mock_hass, basic_config):
        """Test day off (code '0' in pattern)."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # 2025-01-09 is Thursday (offset 3, pattern[3] = '0')
        shift = schedule.get_shift(date(2025, 1, 9))
        
        assert shift is None

    def test_get_shift_pattern_wrapping(self, mock_hass, basic_config):
        """Test pattern wrapping after full cycle."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Pattern has 12 chars, so day 12 should be same as day 0
        shift_day_0 = schedule.get_shift(date(2025, 1, 6))
        shift_day_12 = schedule.get_shift(date(2025, 1, 18))
        
        assert shift_day_0.code == shift_day_12.code

    def test_manual_days_off(self, mock_hass, basic_config):
        """Test manual days off override."""
        basic_config["manual_days_off"] = [
            {"start": "2025-01-06", "end": "2025-01-06"}
        ]
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Day that would normally have shift 1
        shift = schedule.get_shift(date(2025, 1, 6))
        
        assert shift is None

    def test_manual_days_off_range(self, mock_hass, basic_config):
        """Test manual days off as date range."""
        basic_config["manual_days_off"] = [
            {"start": "2025-01-06", "end": "2025-01-10"}
        ]
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # All days in range should be off
        for day_offset in range(5):
            target_day = date(2025, 1, 6) + timedelta(days=day_offset)
            shift = schedule.get_shift(target_day)
            assert shift is None, f"Day {target_day} should be off"

    def test_shift_covering_current_day(self, mock_hass, basic_config):
        """Test shift_covering for a moment within current day shift."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Shift 1 starts at 6:00, check moment at 10:00
        moment = datetime(2025, 1, 6, 10, 0, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
        shift = schedule.shift_covering(moment)
        
        assert shift is not None
        assert shift.code == 1
        assert shift.start <= moment < shift.end

    def test_shift_covering_overnight(self, mock_hass, basic_config):
        """Test shift_covering for overnight shift."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Shift 3 (22:00) from 2025-01-08 ends 2025-01-09 at 6:00
        # Check moment 2025-01-09 at 2:00 (at night)
        moment = datetime(2025, 1, 9, 2, 0, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
        shift = schedule.shift_covering(moment)
        
        assert shift is not None
        assert shift.code == 3  # Shift from previous day
        assert shift.start.date() == date(2025, 1, 8)
        assert shift.end.date() == date(2025, 1, 9)

    def test_next_shift_after(self, mock_hass, basic_config):
        """Test finding next shift after a given moment."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Moment after shift 1 ended should yield shift 2
        moment = datetime(2025, 1, 6, 14, 30, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
        next_shift = schedule.next_shift_after(moment)
        
        assert next_shift is not None
        assert next_shift.code == 2
        assert next_shift.start.hour == 14

    def test_shift_name_default(self, mock_hass, basic_config):
        """Test default shift naming."""
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        assert schedule.shift_name(1) == "Zmiana 1"
        assert schedule.shift_name(2) == "Zmiana 2"
        assert schedule.shift_name(3) == "Zmiana 3"

    def test_shift_name_custom(self, mock_hass, basic_config):
        """Test custom shift names."""
        basic_config["shift_names"] = ["Poranna", "Popołudniowa", "Nocna"]
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        assert schedule.shift_name(1) == "Poranna"
        assert schedule.shift_name(2) == "Popołudniowa"
        assert schedule.shift_name(3) == "Nocna"

    def test_invalid_schedule_start(self, mock_hass, basic_config):
        """Test handling of invalid schedule_start date."""
        basic_config["schedule_start"] = "invalid-date"
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Should fallback to today's date without crash
        assert schedule._base_date is not None

    def test_invalid_timezone_fallback(self, mock_hass, basic_config):
        """Test fallback to UTC for invalid timezone."""
        mock_hass.config.time_zone = "Invalid/Timezone"
        schedule = WorkshiftSchedule(mock_hass, basic_config)
        
        # Should use UTC as fallback
        assert schedule.tz == ZoneInfo("UTC")


@pytest.mark.asyncio
async def test_async_get_default_shift_label():
    """Test async loading of shift labels."""
    mock_hass = Mock()
    mock_hass.config.language = "pl"
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    
    with patch("custom_components.workshift_sensor.schedule._load_shift_label") as mock_load:
        mock_load.return_value = "Zmiana"
        label = await async_get_default_shift_label(mock_hass)
        
        assert label == "Zmiana"
        mock_load.assert_called_once_with("pl")
        mock_hass.async_add_executor_job.assert_awaited()


@pytest.mark.asyncio
async def test_async_get_default_shift_label_fallback():
    """Test fallback to English when Polish translation fails."""
    mock_hass = Mock()
    mock_hass.config.language = "pl"
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    
    with patch("custom_components.workshift_sensor.schedule._load_shift_label") as mock_load:
        mock_load.side_effect = [None, "Shift"]  # PL fails, EN succeeds
        label = await async_get_default_shift_label(mock_hass)
        
        assert label == "Shift"
        assert mock_load.call_count == 2
        assert mock_hass.async_add_executor_job.await_count == 2


@pytest.mark.asyncio
async def test_async_get_default_shift_label_complete_fallback():
    """Test complete fallback to hardcoded 'Shift' when all translations fail."""
    mock_hass = Mock()
    mock_hass.config.language = "pl"
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda func, *args: func(*args))
    
    with patch("custom_components.workshift_sensor.schedule._load_shift_label") as mock_load:
        mock_load.return_value = None  # Both translations fail
        label = await async_get_default_shift_label(mock_hass)
        
        assert label == "Shift"
        assert mock_hass.async_add_executor_job.await_count == 2
