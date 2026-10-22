"""Predicted wind gust sensors, without observation statistics."""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfSpeed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .wind import SmhiWindCoordinator


class SmhiWindGustSensor(CoordinatorEntity[SmhiWindCoordinator], SensorEntity):
    """Next forecast wind gust at its exact source timestamp."""

    _attr_has_entity_name = True
    _attr_translation_key = "wind_gust"
    _attr_device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND
    _attr_icon = "mdi:weather-windy"
    _attr_attribution = "Data provided by SMHI"
    _unrecorded_attributes = frozenset({"current", "forecast"})

    def __init__(self, coordinator: SmhiWindCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> float | int | None:
        return ((self.coordinator.data or {}).get("current") or {}).get("gust")

    @property
    def capability_attributes(self) -> dict[str, Any]:
        return {
            **(super().capability_attributes or {}),
            "source_kind": "local_wind_forecast",
            "wind_unit": UnitOfSpeed.METERS_PER_SECOND,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {
            "created_time": data.get("created_time"),
            "reference_time": data.get("reference_time"),
            "valid_time": (data.get("current") or {}).get("valid_time"),
            "current": data.get("current"),
            "forecast": data.get("forecast", []),
            "max_gust_24h": data.get("max_gust_24h"),
            "max_gust_time": data.get("max_gust_time"),
            "max_window_end": data.get("max_window_end"),
            "max_complete": data.get("max_complete", False),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "data_source_url": data.get("data_source_url"),
        }


class SmhiWindMaxSensor(SmhiWindGustSensor):
    """Maximum of actual source samples across a complete next-24h window."""

    _attr_translation_key = "wind_gust_max_24h"

    @property
    def native_value(self) -> float | int | None:
        data = self.coordinator.data or {}
        return data.get("max_gust_24h") if data.get("max_complete") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            **super().extra_state_attributes,
            "valid_time": (self.coordinator.data or {}).get("max_gust_time"),
        }
