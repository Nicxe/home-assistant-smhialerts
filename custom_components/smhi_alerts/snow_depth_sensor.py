"""Observed snow depth at an explicitly chosen SMHI station."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .snow_depth import SmhiSnowDepthCoordinator


class SmhiSnowDepthSensor(CoordinatorEntity[SmhiSnowDepthCoordinator], SensorEntity):
    """Preserve observation provenance when a measurement becomes unavailable."""

    _attr_has_entity_name = True
    _attr_translation_key = "snow_depth"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_icon = "mdi:snowflake"
    _attr_attribution = "Data provided by SMHI"

    def __init__(
        self, coordinator: SmhiSnowDepthCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_snow_depth"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> float | None:
        return self.coordinator.observation_metadata.get("depth_cm")

    @property
    def capability_attributes(self) -> dict[str, Any]:
        # HA omits dynamic extra attributes during unavailability; provenance
        # belongs here so a card can still label an old observation correctly.
        return {
            **(super().capability_attributes or {}),
            **self.coordinator.observation_metadata,
        }
