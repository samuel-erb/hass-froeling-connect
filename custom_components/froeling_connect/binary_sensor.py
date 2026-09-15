"""Binary sensor platform for Fröling Connect."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import FroelingConnectConfigEntry, FroelingConnectDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FroelingConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Fröling Connect binary sensor entities from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        FroelingConnectBinarySensor(coordinator, key)
        for key, param in coordinator.data.params.items()
        if param.kind == "boolean"
    ]
    async_add_entities(entities)


class FroelingConnectBinarySensor(CoordinatorEntity[FroelingConnectDataUpdateCoordinator], BinarySensorEntity):
    """Representation of a single boolean Fröling Connect value."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: FroelingConnectDataUpdateCoordinator, key: tuple[int, str, str]) -> None:
        super().__init__(coordinator, context=key)
        self._key = key
        facility_id, component_id, _param_id = key

        param = coordinator.data.params[key]
        self._attr_unique_id = f"{facility_id}_{component_id}_{param.param_id}"
        self._attr_name = param.display_text or param.name
        self._attr_device_info = coordinator.component_device_info.get((facility_id, component_id))

        self._update_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_value()
        self.async_write_ha_state()

    def _update_value(self) -> None:
        param = self.coordinator.data.params.get(self._key)
        if param is None:
            self._attr_available = False
            return
        self._attr_available = True
        self._attr_is_on = bool(param.value)
