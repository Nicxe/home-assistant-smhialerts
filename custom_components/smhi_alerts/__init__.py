from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
import logging
from time import monotonic

from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    CONF_DISTRICT,
    CONF_LANGUAGE,
    CONF_INCLUDE_MESSAGES,
    CONF_INCLUDE_GEOMETRY,
    DEFAULT_LANGUAGE,
    DEFAULT_INCLUDE_MESSAGES,
    DEFAULT_INCLUDE_GEOMETRY,
    CONF_MODE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    DEFAULT_MODE,
    DEFAULT_RADIUS_KM,
    CONF_EXCLUDE_SEA,
    DEFAULT_EXCLUDE_SEA,
    CONF_EXCLUDED_MESSAGE_TYPES,
    DEFAULT_EXCLUDED_MESSAGE_TYPES,
    CONF_MESSAGE_TYPES,
    DEFAULT_MESSAGE_TYPES,
)
from .sensor import SmhiAlertCoordinator

_LOGGER = logging.getLogger(__name__)

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
        start = monotonic()
        _LOGGER.debug(
            "Starting coordinator first refresh (entry_id=%s, name=%s)",
            entry.entry_id,
            entry.title,
        )
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.debug(
            "Coordinator first refresh done in %.3fs (entry_id=%s)",
            monotonic() - start,
            entry.entry_id,
        )
    except Exception as ex:
        _LOGGER.debug(
            "Coordinator first refresh failed after %.3fs (entry_id=%s): %s",
            monotonic() - start,
            entry.entry_id,
            ex,
        )
        raise ConfigEntryNotReady from ex

    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator}

    async def _options_updated(hass: HomeAssistant, updated_entry: ConfigEntry):
        domain_data = hass.data.get(DOMAIN, {})
        if updated_entry.entry_id not in domain_data:
            return
        coord = domain_data[updated_entry.entry_id]["coordinator"]
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
        coord.include_geometry = updated_entry.options.get(
            CONF_INCLUDE_GEOMETRY,
            updated_entry.data.get(CONF_INCLUDE_GEOMETRY, DEFAULT_INCLUDE_GEOMETRY),
        )
        coord.set_message_types(
            updated_entry.options.get(
                CONF_MESSAGE_TYPES,
                updated_entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
            ),
            updated_entry.options.get(
                CONF_EXCLUDED_MESSAGE_TYPES,
                updated_entry.data.get(CONF_EXCLUDED_MESSAGE_TYPES, DEFAULT_EXCLUDED_MESSAGE_TYPES),
            ),
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
    updated = False
    data = dict(entry.data)
    options = dict(entry.options)
    version = entry.version

    if entry.version < 2:
        # Default to district mode for existing installations
        if CONF_MODE not in data and CONF_MODE not in options:
            data[CONF_MODE] = DEFAULT_MODE
        version = 2
        updated = True

    if version < 3:
        included = options.get(CONF_MESSAGE_TYPES) or data.get(CONF_MESSAGE_TYPES)
        excluded = options.get(
            CONF_EXCLUDED_MESSAGE_TYPES,
            data.get(CONF_EXCLUDED_MESSAGE_TYPES, DEFAULT_EXCLUDED_MESSAGE_TYPES),
        )
        if not included:
            if excluded:
                included = [
                    code for code in DEFAULT_MESSAGE_TYPES if code not in set(excluded)
                ]
            else:
                included = list(DEFAULT_MESSAGE_TYPES)
        data[CONF_MESSAGE_TYPES] = included
        options.setdefault(CONF_MESSAGE_TYPES, included)
        data.pop(CONF_EXCLUDED_MESSAGE_TYPES, None)
        options.pop(CONF_EXCLUDED_MESSAGE_TYPES, None)
        version = 3
        updated = True

    if version < 4:
        # v4: Stabilize entity unique_id so changing options (including geometry) doesn't create new entities.
        # Old versions derived unique_id from district/coordinates, which caused HA to create new entities
        # on reload when those settings changed or were normalized.
        ent_reg = er.async_get(hass)

        def _pick_best(candidates: list[er.RegistryEntry]) -> er.RegistryEntry | None:
            # Prefer the "primary" entity_id (avoid _2 suffix etc) so existing dashboards keep working.
            if not candidates:
                return None
            def rank(e: er.RegistryEntry) -> tuple[int, str]:
                # Lower is better.
                eid = e.entity_id or ""
                # crude heuristic: entities ending with _2/_3 are likely duplicates.
                dup = 1 if eid.rsplit("_", 1)[-1].isdigit() else 0
                return (dup, eid)
            return sorted(candidates, key=rank)[0]

        def _migrate_platform(domain: str, prefix: str, target_unique_id: str) -> None:
            # If already migrated, do nothing.
            if any(e.unique_id == target_unique_id for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
                return
            candidates = [
                e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
                if e.domain == domain and isinstance(e.unique_id, str) and e.unique_id.startswith(prefix)
            ]
            chosen = _pick_best(candidates)
            if not chosen:
                return
            try:
                ent_reg.async_update_entity(chosen.entity_id, new_unique_id=target_unique_id)
            except TypeError:
                # Older HA versions may not support new_unique_id; in that case we can't auto-migrate.
                _LOGGER.debug("Entity registry does not support new_unique_id; skipping unique_id migration")

        _migrate_platform("sensor", f"{entry.entry_id}_smhi_alert_sensor", f"{entry.entry_id}_smhi_alert_sensor")
        _migrate_platform("binary_sensor", f"{entry.entry_id}_smhi_alert_active", f"{entry.entry_id}_smhi_alert_active")

        version = 4
        updated = True

    if updated:
        hass.config_entries.async_update_entry(entry, data=data, options=options, version=version)
    return True
