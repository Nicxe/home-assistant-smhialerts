"""Local analysis sensors for past one-hour periods, distinct from observations."""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfPrecipitationDepth
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .mesan import SmhiMesanCoordinator


class SmhiMesanSensor(CoordinatorEntity[SmhiMesanCoordinator], SensorEntity):
    """Expose analysed data without assigning observation statistics."""

    _attr_has_entity_name = True
    _attr_attribution = "Data provided by SMHI"
    _unrecorded_attributes = frozenset({"current", "history"})
    _value_key: str

    def __init__(self, coordinator: SmhiMesanCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> float | int | None:
        current = (self.coordinator.data or {}).get("current") or {}
        return current.get(self._value_key)

    @property
    def capability_attributes(self) -> dict[str, Any]:
        """Keep the source selector usable through an initial API outage."""
        return {
            **(super().capability_attributes or {}),
            "source_kind": "local_weather_analysis",
            "precipitation_unit": UnitOfPrecipitationDepth.MILLIMETERS,
            "snow_change_unit": UnitOfLength.CENTIMETERS,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        current = data.get("current") or {}
        return {
            "created_time": data.get("created_time"),
            "reference_time": data.get("reference_time"),
            "valid_time": current.get("valid_time"),
            "current": data.get("current"),
            "history": data.get("history", []),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "data_source_url": data.get("data_source_url"),
        }


class SmhiMesanPrecipitationSensor(SmhiMesanSensor):
    """Analysed precipitation amount for the latest past one-hour period."""

    _attr_translation_key = "analysed_precipitation"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_icon = "mdi:weather-rainy"
    _value_key = "precipitation"


class SmhiMesanSnowChangeSensor(SmhiMesanSensor):
    """Signed snow amount change for the latest past one-hour period."""

    _attr_translation_key = "analysed_snow_change"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_icon = "mdi:snowflake"
    _value_key = "snow_change"
