from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = set()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = data.get("coordinator")
    result: dict[str, Any] = {
        "entry": {
            "data": dict(entry.data),
            "options": dict(entry.options),
            "title": entry.title,
        }
    }
    if coordinator:
        result["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "cached_etag": getattr(coordinator, "_etag", None),
            "cached_last_modified": getattr(coordinator, "_last_modified", None),
            "last_success": getattr(coordinator, "_last_success", None),
            "data": coordinator.data,
        }
    return async_redact_data(result, TO_REDACT)


