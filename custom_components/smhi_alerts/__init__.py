from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_DISTRICT,
    CONF_LANGUAGE,
    CONF_INCLUDE_MESSAGES,
    DEFAULT_LANGUAGE,
    DEFAULT_INCLUDE_MESSAGES,
)
from .sensor import SmhiAlertCoordinator

PLATFORMS: list[str] = ["sensor", "binary_sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the SMHI Alert component."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up SMHI Alert from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create shared coordinator once and store it for all platforms
    coordinator = SmhiAlertCoordinator(hass, entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as ex:
        raise ConfigEntryNotReady from ex

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    async def _options_updated(hass: HomeAssistant, updated_entry: ConfigEntry):
        coord = hass.data[DOMAIN][updated_entry.entry_id]["coordinator"]
        coord.district = updated_entry.options.get(
            CONF_DISTRICT, updated_entry.data.get(CONF_DISTRICT, "all")
        )
        coord.language = updated_entry.options.get(
            CONF_LANGUAGE, updated_entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        )
        coord.include_messages = updated_entry.options.get(
            CONF_INCLUDE_MESSAGES,
            updated_entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
        )
        await coord.async_request_refresh()
        # Request entity/registry to update names immediately
        for platform in PLATFORMS:
            await hass.config_entries.async_forward_entry_unload(updated_entry, platform)
        await hass.config_entries.async_forward_entry_setups(updated_entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_options_updated))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as ex:
        raise ConfigEntryNotReady from ex

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Cleanup domain data for this entry if set by platforms
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unload_ok
