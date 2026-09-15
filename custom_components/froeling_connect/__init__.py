"""The Fröling Connect integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .coordinator import FroelingConnectConfigEntry, FroelingConnectDataUpdateCoordinator

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: FroelingConnectConfigEntry) -> bool:
    """Set up Fröling Connect from a config entry."""
    coordinator = FroelingConnectDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FroelingConnectConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
