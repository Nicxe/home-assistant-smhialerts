"""Entities for local SMHI fire risk forecasts, separate from issued alerts."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .fire_risk import SmhiFireRiskCoordinator

FIRE_RISK_SENSORS = (
    SensorEntityDescription(
        key="forest_fire_risk",
        translation_key="forest_fire_risk",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:pine-tree-fire",
        options=["very_low", "low", "moderate", "high", "very_high", "extreme"],
    ),
    SensorEntityDescription(
        key="grass_fire_risk",
        translation_key="grass_fire_risk",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:grass",
        options=["snow_covered", "season_over", "low", "moderate", "high", "very_high"],
    ),
    SensorEntityDescription(
        key="forest_dryness",
        translation_key="forest_dryness",
        device_class=SensorDeviceClass.ENUM,
        icon="mdi:water-percent",
        options=[
            "very_wet",
            "wet",
            "moderately_wet",
            "dry",
            "very_dry",
            "extremely_dry",
        ],
    ),
)


class SmhiFireRiskSensor(CoordinatorEntity[SmhiFireRiskCoordinator], SensorEntity):
    """One translated risk classification for today's Swedish calendar date."""

    _attr_has_entity_name = True
    _attr_attribution = "Data provided by SMHI"
    _unrecorded_attributes = frozenset({"current", "forecast"})

    def __init__(
        self,
        coordinator: SmhiFireRiskCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        """Attach to the same device while retaining separate availability."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> str | None:
        """Do not turn an absent class into a reassuring low-risk state."""
        current = (self.coordinator.data or {}).get("current") or {}
        return current.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose dated forecast values without affecting official alert counts."""
        data = self.coordinator.data or {}
        current = data.get("current") or {}
        return {
            "source_kind": "local_fire_risk_forecast",
            "approved_time": data.get("approved_time"),
            "reference_time": data.get("reference_time"),
            "valid_time": current.get("valid_time"),
            "forecast_date": current.get("date"),
            "raw_class": current.get(f"{self.entity_description.key}_code"),
            "current": data.get("current"),
            "forecast": data.get("forecast", []),
            "grid_latitude": data.get("grid_latitude"),
            "grid_longitude": data.get("grid_longitude"),
            "data_source_url": data.get("data_source_url"),
        }
