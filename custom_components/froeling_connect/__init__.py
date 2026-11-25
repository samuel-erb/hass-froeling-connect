"""The Fröling Connect integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import LOGGER
from .coordinator import FroelingConnectConfigEntry, FroelingConnectDataUpdateCoordinator
from .migration import RegistryItem, plan_unique_id_migration

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: FroelingConnectConfigEntry) -> bool:
    """Set up Fröling Connect from a config entry."""
    coordinator = FroelingConnectDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _async_migrate_unique_ids(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FroelingConnectConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _async_migrate_unique_ids(
    hass: HomeAssistant, entry: FroelingConnectConfigEntry, coordinator: FroelingConnectDataUpdateCoordinator
) -> None:
    """Move entities from UUID-based to name-based unique IDs (see migration.py)."""
    registry = er.async_get(hass)
    items = [
        RegistryItem(
            entity_id=reg_entry.entity_id,
            unique_id=reg_entry.unique_id,
            original_name=reg_entry.original_name,
            created_at=getattr(reg_entry, "created_at", None),
        )
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id)
    ]
    plan = plan_unique_id_migration(items, coordinator.data.params.values())
    for entity_id in plan.removals:
        LOGGER.info("Removing %s: duplicate created by a Fröling controller software update", entity_id)
        registry.async_remove(entity_id)
    for entity_id, unique_id in plan.renames.items():
        try:
            registry.async_update_entity(entity_id, new_unique_id=unique_id)
        except ValueError:
            LOGGER.warning("Could not migrate unique ID of %s to %s", entity_id, unique_id)
