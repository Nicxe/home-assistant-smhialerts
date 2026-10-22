import asyncio
import logging
from math import isfinite
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, entity_registry as er
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ANALYSIS_ENABLED,
    CONF_ANALYSIS_LOCATION,
    CONF_DISTRICT,
    CONF_EXCLUDE_SEA,
    CONF_EXCLUDED_MESSAGE_TYPES,
    CONF_FIRE_RISK_ENABLED,
    CONF_FIRE_RISK_LOCATION,
    CONF_INCLUDE_GEOMETRY,
    CONF_INCLUDE_MESSAGES,
    CONF_LANGUAGE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MESSAGE_TYPES,
    CONF_MODE,
    CONF_PRECIPITATION_ENABLED,
    CONF_PRECIPITATION_LOCATION,
    CONF_RADIUS_KM,
    CONF_SNOW_DEPTH_ENABLED,
    CONF_SNOW_DEPTH_PARAMETER,
    CONF_SNOW_DEPTH_STATION,
    CONF_THUNDER_PROBABILITY_ENABLED,
    CONF_THUNDER_PROBABILITY_LOCATION,
    CONF_WIND_ENABLED,
    CONF_WIND_LOCATION,
    CONF_WINTER_ENABLED,
    CONF_WINTER_LOCATION,
    DEFAULT_ANALYSIS_ENABLED,
    DEFAULT_EXCLUDE_SEA,
    DEFAULT_EXCLUDED_MESSAGE_TYPES,
    DEFAULT_FIRE_RISK_ENABLED,
    DEFAULT_INCLUDE_GEOMETRY,
    DEFAULT_INCLUDE_MESSAGES,
    DEFAULT_LANGUAGE,
    DEFAULT_MESSAGE_TYPES,
    DEFAULT_MODE,
    DEFAULT_PRECIPITATION_ENABLED,
    DEFAULT_RADIUS_KM,
    DEFAULT_THUNDER_PROBABILITY_ENABLED,
    DEFAULT_WIND_ENABLED,
    DEFAULT_WINTER_ENABLED,
    DOMAIN,
)
from .fire_risk import SmhiFireRiskCoordinator
from .frontend import async_setup_frontend
from .mesan import SmhiMesanCoordinator
from .precipitation import PRECIPITATION_PARAMETERS, SmhiPrecipitationCoordinator
from .runtime_data import SmhiAlertsRuntimeData
from .sensor import SmhiAlertCoordinator
from .snow import SNOW_UPDATE_INTERVAL, SmhiSnowClient
from .snow_depth import SmhiSnowDepthCoordinator
from .thunder import SmhiThunderCoordinator
from .wind import WIND_PARAMETERS, SmhiWindCoordinator
from .winter import WINTER_PARAMETERS, SmhiWinterCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor", "binary_sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _fire_risk_settings(entry: ConfigEntry) -> tuple[bool, float | None, float | None]:
    return _point_forecast_settings(
        entry,
        CONF_FIRE_RISK_ENABLED,
        CONF_FIRE_RISK_LOCATION,
        DEFAULT_FIRE_RISK_ENABLED,
    )


def _thunder_settings(entry: ConfigEntry) -> tuple[bool, float | None, float | None]:
    return _point_forecast_settings(
        entry,
        CONF_THUNDER_PROBABILITY_ENABLED,
        CONF_THUNDER_PROBABILITY_LOCATION,
        DEFAULT_THUNDER_PROBABILITY_ENABLED,
    )


def _winter_settings(entry: ConfigEntry) -> tuple[bool, float | None, float | None]:
    return _point_forecast_settings(
        entry, CONF_WINTER_ENABLED, CONF_WINTER_LOCATION, DEFAULT_WINTER_ENABLED
    )


def _wind_settings(entry: ConfigEntry) -> tuple[bool, float | None, float | None]:
    return _point_forecast_settings(
        entry, CONF_WIND_ENABLED, CONF_WIND_LOCATION, DEFAULT_WIND_ENABLED
    )


def _precipitation_settings(
    entry: ConfigEntry,
) -> tuple[bool, float | None, float | None]:
    return _point_forecast_settings(
        entry,
        CONF_PRECIPITATION_ENABLED,
        CONF_PRECIPITATION_LOCATION,
        DEFAULT_PRECIPITATION_ENABLED,
    )


def _analysis_settings(entry: ConfigEntry) -> tuple[bool, float | None, float | None]:
    return _point_forecast_settings(
        entry, CONF_ANALYSIS_ENABLED, CONF_ANALYSIS_LOCATION, DEFAULT_ANALYSIS_ENABLED
    )


def _snow_depth_settings(entry: ConfigEntry) -> tuple[bool, str | None, str | None]:
    """Require an explicit station and source; never substitute another station."""
    current = {**entry.data, **entry.options}
    enabled = bool(current.get(CONF_SNOW_DEPTH_ENABLED, False))
    station = current.get(CONF_SNOW_DEPTH_STATION)
    parameter = current.get(CONF_SNOW_DEPTH_PARAMETER)
    if not enabled:
        return False, None, None
    if (
        not isinstance(station, str)
        or not station.isascii()
        or not station.isdigit()
        or parameter not in ("8", "52")
    ):
        return True, None, None
    return True, station, parameter


def _point_forecast_settings(
    entry: ConfigEntry, enabled_key: str, location_key: str, default: bool
) -> tuple[bool, float | None, float | None]:
    """Read the explicitly configured point without assuming a district centre."""
    enabled = entry.options.get(enabled_key, entry.data.get(enabled_key, default))
    location = entry.options.get(location_key, entry.data.get(location_key))
    if not enabled or not isinstance(location, dict):
        return bool(enabled), None, None
    if any(
        isinstance(location.get(key), bool) for key in (CONF_LATITUDE, CONF_LONGITUDE)
    ):
        return True, None, None
    try:
        latitude = float(location[CONF_LATITUDE])
        longitude = float(location[CONF_LONGITUDE])
    except (KeyError, TypeError, ValueError, OverflowError):
        return True, None, None
    if not (
        isfinite(latitude)
        and isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return True, None, None
    return True, latitude, longitude


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the SMHI Alert component."""
    hass.data.setdefault(DOMAIN, {})
    await async_setup_frontend(hass)
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

    fire_settings = _fire_risk_settings(entry)
    thunder_settings = _thunder_settings(entry)
    winter_settings = _winter_settings(entry)
    snow_depth_settings = _snow_depth_settings(entry)
    wind_settings = _wind_settings(entry)
    precipitation_settings = _precipitation_settings(entry)
    analysis_settings = _analysis_settings(entry)
    fire_coordinator = None
    thunder_coordinator = None
    winter_coordinator = None
    snow_depth_coordinator = None
    wind_coordinator = None
    precipitation_coordinator = None
    analysis_coordinator = None
    # Share only enabled SNOW parameters at the same explicitly chosen point.
    point_parameters: dict[tuple[float, float], set[str]] = {}
    for settings, parameters in (
        (thunder_settings, ("thunderstorm_probability",)),
        (winter_settings, WINTER_PARAMETERS),
        (wind_settings, WIND_PARAMETERS),
        (precipitation_settings, PRECIPITATION_PARAMETERS),
    ):
        enabled, latitude, longitude = settings
        if enabled and latitude is not None and longitude is not None:
            point_parameters.setdefault((latitude, longitude), set()).update(parameters)
    point_clients = {
        point: SmhiSnowClient(
            aiohttp_client.async_get_clientsession(hass),
            *point,
            parameters=tuple(sorted(parameters)),
            cache_interval=SNOW_UPDATE_INTERVAL,
        )
        for point, parameters in point_parameters.items()
    }
    enabled, latitude, longitude = fire_settings
    if enabled and latitude is not None and longitude is not None:
        fire_coordinator = SmhiFireRiskCoordinator(hass, entry, latitude, longitude)
    elif enabled:
        _LOGGER.warning(
            "Fire risk requires a valid location; choose a location in integration options"
        )
    enabled, latitude, longitude = thunder_settings
    if enabled and latitude is not None and longitude is not None:
        thunder_coordinator = SmhiThunderCoordinator(
            hass,
            entry,
            latitude,
            longitude,
            client=point_clients.get(thunder_settings[1:]),
        )
    elif enabled:
        _LOGGER.warning(
            "Thunderstorm probability requires a valid location; choose a location in integration options"
        )
    enabled, latitude, longitude = winter_settings
    if enabled and latitude is not None and longitude is not None:
        winter_coordinator = SmhiWinterCoordinator(
            hass,
            entry,
            latitude,
            longitude,
            client=point_clients.get(winter_settings[1:]),
        )
    elif enabled:
        _LOGGER.warning(
            "Winter forecasts require a valid location; choose a location in integration options"
        )
    enabled, station_id, parameter = snow_depth_settings
    if enabled and station_id is not None and parameter is not None:
        snow_depth_coordinator = SmhiSnowDepthCoordinator(
            hass,
            entry,
            station_id,
            parameter,
            latitude=hass.config.latitude,
            longitude=hass.config.longitude,
        )
    elif enabled:
        _LOGGER.warning(
            "Snow depth requires a station; choose a station in integration options"
        )
    enabled, latitude, longitude = wind_settings
    if enabled and latitude is not None and longitude is not None:
        wind_coordinator = SmhiWindCoordinator(
            hass,
            entry,
            latitude,
            longitude,
            client=point_clients.get(wind_settings[1:]),
        )
    elif enabled:
        _LOGGER.warning(
            "Wind forecasts require a valid location in integration options"
        )
    enabled, latitude, longitude = precipitation_settings
    if enabled and latitude is not None and longitude is not None:
        precipitation_coordinator = SmhiPrecipitationCoordinator(
            hass,
            entry,
            latitude,
            longitude,
            client=point_clients.get(precipitation_settings[1:]),
        )
    elif enabled:
        _LOGGER.warning(
            "Precipitation forecasts require a valid location in integration options"
        )
    enabled, latitude, longitude = analysis_settings
    if enabled and latitude is not None and longitude is not None:
        analysis_coordinator = SmhiMesanCoordinator(hass, entry, latitude, longitude)
    elif enabled:
        _LOGGER.warning(
            "Weather analysis requires a valid location in integration options"
        )
    # Optional sources refresh independently and retry through their entity
    # subscriptions. Their availability never controls the issued warnings.
    await asyncio.gather(
        *(
            optional.async_refresh()
            for optional in (
                fire_coordinator,
                thunder_coordinator,
                winter_coordinator,
                snow_depth_coordinator,
                wind_coordinator,
                precipitation_coordinator,
                analysis_coordinator,
            )
            if optional is not None
        )
    )
    entry.runtime_data = SmhiAlertsRuntimeData(
        warnings=coordinator,
        fire_risk=fire_coordinator,
        fire_risk_settings=fire_settings,
        thunder=thunder_coordinator,
        thunder_settings=thunder_settings,
        winter=winter_coordinator,
        winter_settings=winter_settings,
        snow_depth=snow_depth_coordinator,
        snow_depth_settings=snow_depth_settings,
        wind=wind_coordinator,
        wind_settings=wind_settings,
        precipitation=precipitation_coordinator,
        precipitation_settings=precipitation_settings,
        analysis=analysis_coordinator,
        analysis_settings=analysis_settings,
    )

    async def _options_updated(hass: HomeAssistant, updated_entry: ConfigEntry):
        domain_data = hass.data.get(DOMAIN, {})
        if updated_entry.entry_id not in domain_data:
            return
        if (
            _fire_risk_settings(updated_entry)
            != updated_entry.runtime_data.fire_risk_settings
            or _thunder_settings(updated_entry)
            != updated_entry.runtime_data.thunder_settings
            or _winter_settings(updated_entry)
            != updated_entry.runtime_data.winter_settings
            or _snow_depth_settings(updated_entry)
            != updated_entry.runtime_data.snow_depth_settings
            or _wind_settings(updated_entry) != updated_entry.runtime_data.wind_settings
            or _precipitation_settings(updated_entry)
            != updated_entry.runtime_data.precipitation_settings
            or _analysis_settings(updated_entry)
            != updated_entry.runtime_data.analysis_settings
        ):
            await hass.config_entries.async_reload(updated_entry.entry_id)
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
                updated_entry.data.get(
                    CONF_EXCLUDED_MESSAGE_TYPES, DEFAULT_EXCLUDED_MESSAGE_TYPES
                ),
            ),
        )
        coord.exclude_sea = updated_entry.options.get(
            CONF_EXCLUDE_SEA,
            updated_entry.data.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA),
        )
        coord.latitude = float(
            updated_entry.options.get(
                CONF_LATITUDE,
                updated_entry.data.get(CONF_LATITUDE, hass.config.latitude),
            )
        )
        coord.longitude = float(
            updated_entry.options.get(
                CONF_LONGITUDE,
                updated_entry.data.get(CONF_LONGITUDE, hass.config.longitude),
            )
        )
        coord.radius_km = float(
            updated_entry.options.get(
                CONF_RADIUS_KM,
                updated_entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
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
            if any(
                e.unique_id == target_unique_id
                for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
            ):
                return
            candidates = [
                e
                for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
                if e.domain == domain
                and isinstance(e.unique_id, str)
                and e.unique_id.startswith(prefix)
            ]
            chosen = _pick_best(candidates)
            if not chosen:
                return
            try:
                ent_reg.async_update_entity(
                    chosen.entity_id, new_unique_id=target_unique_id
                )
            except TypeError:
                # Older HA versions may not support new_unique_id; in that case we can't auto-migrate.
                _LOGGER.debug(
                    "Entity registry does not support new_unique_id; skipping unique_id migration"
                )

        _migrate_platform(
            "sensor",
            f"{entry.entry_id}_smhi_alert_sensor",
            f"{entry.entry_id}_smhi_alert_sensor",
        )
        _migrate_platform(
            "binary_sensor",
            f"{entry.entry_id}_smhi_alert_active",
            f"{entry.entry_id}_smhi_alert_active",
        )

        version = 4
        updated = True

    if updated:
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=version
        )
    return True
