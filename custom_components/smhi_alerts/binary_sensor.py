import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, DISTRICTS, DEFAULT_NAME, DEFAULT_MODE, DEFAULT_RADIUS_KM

_LOGGER = logging.getLogger(__name__)

# Platform should not parallelize updates since coordinator handles all fetching
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    try:
        coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    except KeyError:
        _LOGGER.error("Coordinator not available during binary_sensor setup")
        return
    async_add_entities([SMHIAlertBinarySensor(coordinator, entry)], True)


class SMHIAlertBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.district = coordinator.district
        self.language = coordinator.language
        self._attr_name = self._derive_name()
        self._attr_device_class = "problem"
        self._attr_icon = "mdi:alert-circle"
        self._attr_unique_id = self._derive_unique_id()
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": self._attr_name,
            "manufacturer": "Nicxe",
            "entry_type": DeviceEntryType.SERVICE,
        }

    @property
    def is_on(self) -> bool:
        attributes: dict[str, Any] = self.coordinator.data.get("attributes", {})
        return (attributes.get("alerts_count") or 0) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        src = self.coordinator.data.get("attributes", {})
        # Keep binary sensor attributes minimal; avoid heavy message payloads
        return {
            "warnings_count": src.get("warnings_count", 0),
            "messages_count": src.get("messages_count", 0),
            "alerts_count": src.get("alerts_count", 0),
            "highest_severity": src.get("highest_severity", "NONE"),
            "last_update": src.get("last_update"),
            "attribution": src.get("attribution"),
        }

    def _derive_name(self) -> str:
        if getattr(self.coordinator, "mode", DEFAULT_MODE) == "coordinate":
            lat = round(getattr(self.coordinator, "latitude", 0.0), 4)
            lon = round(getattr(self.coordinator, "longitude", 0.0), 4)
            r = int(round(getattr(self.coordinator, "radius_km", DEFAULT_RADIUS_KM)))
            return f"{DEFAULT_NAME} active ({lat},{lon} @ {r}km)"
        else:
            return (
                f"{DEFAULT_NAME} active ({DISTRICTS.get(self.district, self.district)})"
            )

    def _derive_unique_id(self) -> str:
        # IMPORTANT: unique_id must be stable for the lifetime of the config entry.
        # Do NOT include user-configurable settings (district/coordinates/radius/language/geometry),
        # otherwise HA will create new entities when those settings change.
        return f"{self.entry.entry_id}_smhi_alert_active"
