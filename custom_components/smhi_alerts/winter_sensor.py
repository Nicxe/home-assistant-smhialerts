"""Local winter forecast entities, distinct from measurements and warnings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .winter import PRECIPITATION_TYPES, SmhiWinterCoordinator


class SmhiWinterSensor(CoordinatorEntity[SmhiWinterCoordinator], SensorEntity):
    """Share source data while preserving each parameter's independent unknowns."""

    _attr_has_entity_name = True
    _attr_attribution = "Data provided by SMHI"
    _unrecorded_attributes = frozenset({"current", "forecast"})
    _value_key: str

    def __init__(self, coordinator: SmhiWinterCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> str | float | int | None:
        current = (self.coordinator.data or {}).get("current") or {}
        return current.get(self._value_key)

    @property
    def capability_attributes(self) -> dict[str, Any]:
        """Identify the source and native forecast units even during an outage."""
        return {
            **(super().capability_attributes or {}),
            "source_kind": "local_winter_forecast",
            "probability_unit": PERCENTAGE,
            "temperature_unit": UnitOfTemperature.CELSIUS,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        current = data.get("current") or {}
        return {
            "created_time": data.get("created_time"),
            "reference_time": data.get("reference_time"),
            "valid_time": current.get("valid_time"),
            "precipitation_type_code": current.get("precipitation_type_code"),
            "current": data.get("current"),
            "forecast": data.get("forecast", []),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "data_source_url": data.get("data_source_url"),
        }


class SmhiWinterPrecipitationSensor(SmhiWinterSensor):
    """SMHI's predominant precipitation type at the next forecast time."""

    _attr_translation_key = "winter_precipitation_type"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(PRECIPITATION_TYPES)
    _attr_icon = "mdi:weather-snowy-rainy"
    _value_key = "precipitation_type"


class SmhiWinterProbabilitySensor(SmhiWinterSensor):
    """Frozen precipitation probability at the next forecast time."""

    _attr_translation_key = "winter_frozen_probability"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:snowflake"
    _value_key = "frozen_probability"


class SmhiWinterTemperatureSensor(SmhiWinterSensor):
    """Air temperature forecast without observation statistics."""

    _attr_translation_key = "winter_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_icon = "mdi:thermometer"
    _value_key = "temperature"
