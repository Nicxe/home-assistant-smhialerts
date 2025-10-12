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
    CONF_MODE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    DEFAULT_MODE,
    DEFAULT_RADIUS_KM,
    CONF_EXCLUDE_SEA,
    DEFAULT_EXCLUDE_SEA,
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
        coord.mode = updated_entry.options.get(
            CONF_MODE, updated_entry.data.get(CONF_MODE, DEFAULT_MODE)
        )
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
        coord.exclude_sea = updated_entry.options.get(
            CONF_EXCLUDE_SEA,
            updated_entry.data.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA),
        )
        coord.latitude = float(
            updated_entry.options.get(
                CONF_LATITUDE, updated_entry.data.get(CONF_LATITUDE, hass.config.latitude)
            )
        )
        coord.longitude = float(
            updated_entry.options.get(
                CONF_LONGITUDE, updated_entry.data.get(CONF_LONGITUDE, hass.config.longitude)
            )
        )
        coord.radius_km = float(
            updated_entry.options.get(
                CONF_RADIUS_KM, updated_entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
            )
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to newer version."""
    # We bumped ConfigFlow.VERSION to 2 to introduce filter mode and coordinates.
    if entry.version < 2:
        data = dict(entry.data)
        options = dict(entry.options)
        # Default to district mode for existing installations
        if CONF_MODE not in data and CONF_MODE not in options:
            data[CONF_MODE] = DEFAULT_MODE
        # No coordinate defaults needed unless chosen later in options
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
