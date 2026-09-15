"""Sensor platform for Fröling Connect."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfMass, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .coordinator import FroelingConnectConfigEntry, FroelingConnectDataUpdateCoordinator

# Maps the API's `unit` string to a HA device class + native unit of measurement.
# Anything not listed here is still shown, just without a device class (unit as-is).
UNIT_MAP: dict[str, tuple[SensorDeviceClass | None, str]] = {
    "°C": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
    "°F": (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT),
    "h": (SensorDeviceClass.DURATION, UnitOfTime.HOURS),
    "t": (SensorDeviceClass.WEIGHT, UnitOfMass.METRIC_TONS),
    "kg": (SensorDeviceClass.WEIGHT, UnitOfMass.KILOGRAMS),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FroelingConnectConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Fröling Connect sensor entities from a config entry."""
    coordinator = entry.runtime_data
    entities = [
        FroelingConnectSensor(coordinator, key)
        for key, param in coordinator.data.params.items()
        if param.kind in ("numeric", "enum", "text")
    ]
    async_add_entities(entities)


class FroelingConnectSensor(CoordinatorEntity[FroelingConnectDataUpdateCoordinator], SensorEntity):
    """Representation of a single Fröling Connect value."""

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

        if param.kind == "numeric":
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if param.unit in UNIT_MAP:
                device_class, unit = UNIT_MAP[param.unit]
                self._attr_device_class = device_class
                self._attr_native_unit_of_measurement = unit
            elif param.unit:
                self._attr_native_unit_of_measurement = param.unit
        elif param.kind == "enum":
            self._attr_device_class = SensorDeviceClass.ENUM
            if param.options:
                self._attr_options = list(param.options.values())

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
        if param.kind == "enum" and param.options:
            self._attr_native_value = param.options.get(param.value, param.value)
        else:
            self._attr_native_value = param.value
