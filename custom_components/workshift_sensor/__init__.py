"""The Workshift Sensor integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .util import WorkshiftConfigData

_LOGGER = logging.getLogger(__name__)


def _config_from_entry(entry: ConfigEntry) -> WorkshiftConfigData:
    """Build a WorkshiftConfigData instance from a config entry."""
    fallback = (
        entry.options.get(CONF_NAME)
        or entry.data.get(CONF_NAME)
        or entry.title
        or ""
    )
    merged = {**entry.data, **entry.options}
    return WorkshiftConfigData.from_mapping(merged, fallback_name=fallback)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML (not supported)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Workshift Sensor from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _config_from_entry(entry)
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
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _config_from_entry(entry)
    await hass.config_entries.async_reload(entry.entry_id)
