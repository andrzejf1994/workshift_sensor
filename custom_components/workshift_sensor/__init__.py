"""The Workshift Sensor integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

DOMAIN = "workshift_sensor"
PLATFORMS: list[str] = ["sensor", "binary_sensor", "calendar"]

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML (not supported)."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Workshift Sensor from a config entry."""
    from .schedule import async_get_default_shift_label

    config: dict = {**entry.data, **entry.options}
    
    # FIX #3: Error handling for translation loading
    try:
        config["default_shift_label"] = await async_get_default_shift_label(hass)
    except Exception as err:
        _LOGGER.warning(
            "Failed to load localized shift label, using fallback 'Shift': %s", 
            err
        )
        config["default_shift_label"] = "Shift"
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = config
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # FIX #2: Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update - reload the integration."""
    await hass.config_entries.async_reload(entry.entry_id)
