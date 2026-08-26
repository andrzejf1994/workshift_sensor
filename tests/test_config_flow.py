"""Tests for current Home Assistant config-flow contracts."""

from unittest.mock import Mock

import pytest
import voluptuous as vol

from homeassistant.config_entries import OptionsFlow

from custom_components.workshift_sensor.config_flow import (
    WorkshiftConfigFlow,
    WorkshiftOptionsFlowHandler,
    _overlaps_schedule_override,
    _parse_schedule_override,
)


def test_options_flow_factory_returns_a_flow_not_a_coroutine():
    """HA invokes the options-flow factory synchronously."""
    flow = WorkshiftConfigFlow.async_get_options_flow(Mock())

    assert isinstance(flow, OptionsFlow)
    assert isinstance(flow, WorkshiftOptionsFlowHandler)


def test_substitute_schedule_override_is_normalized_and_cannot_overlap():
    """Substitute schedules must have a valid non-overlapping date range."""
    override = _parse_schedule_override("2026-06-01", "2026-06-07", "120", 3)

    assert override == {
        "start": "2026-06-01",
        "end": "2026-06-07",
        "schedule": "120",
    }
    assert _overlaps_schedule_override(
        {"start": "2026-06-07", "end": "2026-06-10", "schedule": "2"},
        [override],
    )

    with pytest.raises(vol.Invalid):
        _parse_schedule_override("2026-06-08", "2026-06-07", "1", 3)
