"""Tests for current Home Assistant config-flow contracts."""

from unittest.mock import Mock

from homeassistant.config_entries import OptionsFlow

from custom_components.workshift_sensor.config_flow import (
    WorkshiftConfigFlow,
    WorkshiftOptionsFlowHandler,
)


def test_options_flow_factory_returns_a_flow_not_a_coroutine():
    """HA invokes the options-flow factory synchronously."""
    flow = WorkshiftConfigFlow.async_get_options_flow(Mock())

    assert isinstance(flow, OptionsFlow)
    assert isinstance(flow, WorkshiftOptionsFlowHandler)
