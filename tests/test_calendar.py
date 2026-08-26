"""Tests for calendar query behavior."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from custom_components.workshift_sensor.calendar import WorkshiftCalendarEntity


@pytest.mark.asyncio
async def test_calendar_does_not_truncate_a_long_requested_range():
    """Calendar consumers must receive events for their complete range."""
    calendar = object.__new__(WorkshiftCalendarEntity)
    timezone = ZoneInfo("Europe/Warsaw")
    calendar._ensure_local = lambda value: value.astimezone(timezone)
    calendar._compute_events_blocking = Mock(return_value=[])
    hass = Mock()
    hass.async_add_executor_job = AsyncMock(
        side_effect=lambda func, *args: func(*args)
    )
    start = datetime(2026, 1, 1, tzinfo=timezone)
    end = start + timedelta(days=120)

    result = await calendar.async_get_events(hass, start, end)

    assert result == []
    hass.async_add_executor_job.assert_awaited_once_with(
        calendar._compute_events_blocking, start, end
    )
