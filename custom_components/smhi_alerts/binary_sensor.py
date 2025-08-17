import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import DOMAIN, DISTRICTS, DEFAULT_NAME

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
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
        self._attr_name = f"{DEFAULT_NAME} active ({DISTRICTS.get(self.district, self.district)})"
        self._attr_device_class = "problem"
        self._attr_icon = "mdi:alert-circle"
        self._attr_unique_id = f"{entry.entry_id}_smhi_alert_active_{self.district}"
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


