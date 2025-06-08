from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from .const import DOMAIN

# Import the sensor platform so Home Assistant registers it before
# forward_entry_setups is called. This avoids potential setup blocking
# when the integration forwards the config entry to the sensor platform.
from . import sensor

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the SMHI Alert component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up SMHI Alert from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    try:
        # Forward the config entry to the sensor platform. The import above
        # ensures the platform is registered and prevents setup from blocking.
        await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    except Exception as ex:
        raise ConfigEntryNotReady from ex

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])

    if unload_ok:
        # Remove update listener if it was registered
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, {})
        update_listener = entry_data.get("update_listener")
        if update_listener:
            update_listener()

    return unload_ok
