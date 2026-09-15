"""Data update coordinator for Fröling Connect."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FacilityInfo, FroelingApiError, FroelingAuthError, FroelingConnectClient, Param
from .const import DEFAULT_UPDATE_INTERVAL_SECONDS, DOMAIN, LOGGER

type FroelingConnectConfigEntry = ConfigEntry[FroelingConnectDataUpdateCoordinator]


@dataclass
class FroelingConnectData:
    """All parameters read from all facilities, keyed by (facility_id, component_id, param_id)."""

    params: dict[tuple[int, str, str], Param] = field(default_factory=dict)


class FroelingConnectDataUpdateCoordinator(DataUpdateCoordinator[FroelingConnectData]):
    """Fetches every facility/component/parameter on a fixed interval."""

    config_entry: FroelingConnectConfigEntry

    def __init__(self, hass: HomeAssistant, entry: FroelingConnectConfigEntry) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_UPDATE_INTERVAL_SECONDS),
        )
        self.client = FroelingConnectClient(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        self.facilities: dict[int, FacilityInfo] = {}
        self.component_device_info: dict[tuple[int, str], DeviceInfo] = {}
        self.component_names: dict[tuple[int, str], str] = {}

    async def _async_update_data(self) -> FroelingConnectData:
        try:
            facilities = await self.client.get_facilities()
        except FroelingAuthError as err:
            raise ConfigEntryAuthFailed from err
        except FroelingApiError as err:
            raise UpdateFailed(str(err)) from err

        params: dict[tuple[int, str, str], Param] = {}
        device_registry = dr.async_get(self.hass)

        for facility in facilities:
            self.facilities[facility.facility_id] = facility
            self._register_facility_device(device_registry, facility)

            for param in self.client.get_facility_info_params(facility):
                params[(facility.facility_id, param.component_id, param.param_id)] = param
            self.component_device_info[(facility.facility_id, "facility_info")] = self._facility_device_info(facility)
            self.component_names[(facility.facility_id, "facility_info")] = "Anlageninfo"

            try:
                components = await self.client.get_components(facility)
            except FroelingApiError as err:
                raise UpdateFailed(str(err)) from err

            for component in components:
                key = (facility.facility_id, component.component_id)
                self.component_device_info[key] = self._component_device_info(facility, component)
                self.component_names[key] = component.name
                try:
                    component_params = await self.client.get_component_params(facility, component)
                except FroelingApiError:
                    LOGGER.exception("Failed to fetch parameters for component %s", component.component_id)
                    continue
                for param in component_params:
                    params[(facility.facility_id, param.component_id, param.param_id)] = param

        return FroelingConnectData(params=params)

    def _register_facility_device(self, device_registry: dr.DeviceRegistry, facility: FacilityInfo) -> None:
        device_registry.async_get_or_create(
            config_entry_id=self.config_entry.entry_id,
            identifiers={(DOMAIN, f"facility_{facility.facility_id}")},
            name=facility.name,
            manufacturer="Fröling",
            model=facility.generation,
        )

    def _facility_device_info(self, facility: FacilityInfo) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"facility_{facility.facility_id}")},
            name=facility.name,
            manufacturer="Fröling",
            model=facility.generation,
        )

    def _component_device_info(self, facility: FacilityInfo, component) -> DeviceInfo:  # noqa: ANN001
        return DeviceInfo(
            identifiers={(DOMAIN, f"component_{facility.facility_id}_{component.component_id}")},
            name=component.name,
            manufacturer="Fröling",
            model=component.model,
            via_device=(DOMAIN, f"facility_{facility.facility_id}"),
        )
