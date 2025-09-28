"""The Workshift Sensor integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

DOMAIN = "workshift_sensor"
PLATFORMS: list[str] = ["sensor", "binary_sensor"]

_LOGGER = logging.getLogger(__name__)


def _merged_entry_data(entry: ConfigEntry) -> dict[str, Any]:
    """Return config entry data with options merged in."""
    data: dict[str, Any] = dict(entry.data)
    if entry.options:
        data.update(entry.options)
    return data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Workshift Sensor from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _merged_entry_data(entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle updates to the config entry options."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _merged_entry_data(entry)
    await hass.config_entries.async_reload(entry.entry_id)