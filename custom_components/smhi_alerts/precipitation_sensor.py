"""Predicted precipitation for complete, explicitly dated source intervals."""

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPrecipitationDepth
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .precipitation import SmhiPrecipitationCoordinator


class SmhiPrecipitationProbabilitySensor(
    CoordinatorEntity[SmhiPrecipitationCoordinator], SensorEntity
):
    """Probability over the complete source interval ending at the forecast time."""

    _attr_has_entity_name = True
    _attr_translation_key = "precipitation_probability"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:weather-rainy"
    _attr_attribution = "Data provided by SMHI"
    _unrecorded_attributes = frozenset({"current", "forecast"})
    _value_key = "probability"

    def __init__(
        self, coordinator: SmhiPrecipitationCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{self._attr_translation_key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> float | int | None:
        return ((self.coordinator.data or {}).get("current") or {}).get(self._value_key)

    @property
    def capability_attributes(self) -> dict[str, Any]:
        return {
            **(super().capability_attributes or {}),
            "source_kind": "local_precipitation_forecast",
            "probability_unit": PERCENTAGE,
            "amount_unit": UnitOfPrecipitationDepth.MILLIMETERS,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        current = data.get("current") or {}
        return {
            "created_time": data.get("created_time"),
            "reference_time": data.get("reference_time"),
            "valid_time": current.get("valid_time"),
            "interval_start": current.get("interval_start"),
            "current": data.get("current"),
            "forecast": data.get("forecast", []),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "data_source_url": data.get("data_source_url"),
        }


class SmhiPrecipitationAmountSensor(SmhiPrecipitationProbabilitySensor):
    """Water-equivalent millimetres for the full source interval, never mm/h."""

    _attr_translation_key = "precipitation_amount"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _value_key = "amount"
