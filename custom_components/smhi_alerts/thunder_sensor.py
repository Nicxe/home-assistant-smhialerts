"""Local thunderstorm probability at SMHI's next forecast time."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .thunder import SmhiThunderCoordinator


class SmhiThunderSensor(CoordinatorEntity[SmhiThunderCoordinator], SensorEntity):
    """Keep a forecast percentage distinct from observations and issued warnings."""

    _attr_has_entity_name = True
    _attr_translation_key = "thunder_probability"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:weather-lightning"
    _attr_attribution = "Data provided by SMHI"
    _unrecorded_attributes = frozenset({"current", "forecast"})

    def __init__(self, coordinator: SmhiThunderCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_thunder_probability"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> float | None:
        """Missing probability is unknown; zero is a valid forecast."""
        current = (self.coordinator.data or {}).get("current") or {}
        return current.get("probability")

    @property
    def capability_attributes(self) -> dict[str, Any]:
        """Keep the card's source selector usable during an initial API outage."""
        return {
            **(super().capability_attributes or {}),
            "source_kind": "local_thunder_probability_forecast",
            "probability_unit": PERCENTAGE,
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the exact forecast time and bounded upcoming source values."""
        data = self.coordinator.data or {}
        current = data.get("current") or {}
        return {
            "created_time": data.get("created_time"),
            "reference_time": data.get("reference_time"),
            "valid_time": current.get("valid_time"),
            "current": data.get("current"),
            "forecast": data.get("forecast", []),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "data_source_url": data.get("data_source_url"),
        }
