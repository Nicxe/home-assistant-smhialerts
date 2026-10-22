from collections.abc import Mapping
import math

from aiohttp import ClientError, ClientTimeout
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import selector
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import (
    AREAS_URL,
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
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_MESSAGE_TYPES,
    CONF_MODE,
    CONF_PRECIPITATION_ENABLED,
    CONF_PRECIPITATION_LOCATION,
    CONF_RADIUS_KM,
    CONF_SNOW_DEPTH_CHANGE_STATION,
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
    DEFAULT_SNOW_DEPTH_ENABLED,
    DEFAULT_SNOW_DEPTH_PARAMETER,
    DEFAULT_THUNDER_PROBABILITY_ENABLED,
    DEFAULT_WIND_ENABLED,
    DEFAULT_WINTER_ENABLED,
    DISTRICTS,
    DOMAIN,
    LANGUAGE_OPTIONS,
    MESSAGE_EVENT_CATEGORIES,
)


def _build_message_multiselect_options() -> dict[str, str]:
    options: dict[str, str] = {}
    for item in MESSAGE_EVENT_CATEGORIES:
        sv = item.get("label_sv") or ""
        en = item.get("label_en") or ""
        if sv and en and sv.lower() != en.lower():
            label = f"{sv} / {en}"
        else:
            label = sv or en or item["value"]
        options[item["value"]] = label
    return options


def _resolve_entry_message_types(entry):
    included = entry.options.get(
        CONF_MESSAGE_TYPES,
        entry.data.get(CONF_MESSAGE_TYPES),
    )
    if not included:
        excluded = entry.options.get(
            CONF_EXCLUDED_MESSAGE_TYPES,
            entry.data.get(CONF_EXCLUDED_MESSAGE_TYPES, DEFAULT_EXCLUDED_MESSAGE_TYPES),
        )
        if excluded:
            included = [code for code in DEFAULT_MESSAGE_TYPES if code not in excluded]
    if not included:
        included = DEFAULT_MESSAGE_TYPES
    return included


def _location_from_input(user_input, default_latitude, default_longitude):
    """Return a normalized location dict from selector input."""
    loc = user_input.get(CONF_LOCATION) or {}
    latitude = loc.get("latitude", default_latitude)
    longitude = loc.get("longitude", default_longitude)
    return {"latitude": latitude, "longitude": longitude}


_LOCAL_FORECAST_OPTIONS = (
    (CONF_WIND_ENABLED, CONF_WIND_LOCATION, DEFAULT_WIND_ENABLED),
    (
        CONF_PRECIPITATION_ENABLED,
        CONF_PRECIPITATION_LOCATION,
        DEFAULT_PRECIPITATION_ENABLED,
    ),
    (CONF_ANALYSIS_ENABLED, CONF_ANALYSIS_LOCATION, DEFAULT_ANALYSIS_ENABLED),
    (CONF_FIRE_RISK_ENABLED, CONF_FIRE_RISK_LOCATION, DEFAULT_FIRE_RISK_ENABLED),
    (
        CONF_THUNDER_PROBABILITY_ENABLED,
        CONF_THUNDER_PROBABILITY_LOCATION,
        DEFAULT_THUNDER_PROBABILITY_ENABLED,
    ),
    (CONF_WINTER_ENABLED, CONF_WINTER_LOCATION, DEFAULT_WINTER_ENABLED),
)


def _forecast_location(user_input, enabled_key, location_key):
    """Validate a separately selected forecast point without guessing coverage."""
    location = user_input.get(location_key)
    if not location and not user_input.get(enabled_key, False):
        return None
    error = f"invalid_{location_key}"
    if not isinstance(location, Mapping):
        raise ValueError(error)
    result = {}
    for key, limit in (("latitude", 90), ("longitude", 180)):
        value = location.get(key)
        if isinstance(value, bool):
            raise ValueError(error)
        try:
            coordinate = float(value)
        except (TypeError, ValueError, OverflowError) as err:
            raise ValueError(error) from err
        if not math.isfinite(coordinate) or not -limit <= coordinate <= limit:
            raise ValueError(error)
        result[key] = coordinate
    return result


def _local_forecast_errors(user_input):
    """Return separate field errors before persisting invalid forecast points."""
    errors = {}
    for enabled_key, location_key, _default in _LOCAL_FORECAST_OPTIONS:
        try:
            _forecast_location(user_input, enabled_key, location_key)
        except ValueError:
            errors[location_key] = f"invalid_{location_key}"
    return errors


def _local_forecast_schema(hass, entry=None):
    """Show an independent point for each optional forecast source."""
    current = {**entry.data, **entry.options} if entry else {}
    schema = {}
    for enabled_key, location_key, default in _LOCAL_FORECAST_OPTIONS:
        schema[vol.Required(enabled_key, default=current.get(enabled_key, default))] = (
            cv.boolean
        )
        schema[
            vol.Optional(
                location_key,
                description={
                    "suggested_value": current.get(
                        location_key,
                        {
                            "latitude": hass.config.latitude,
                            "longitude": hass.config.longitude,
                        },
                    )
                },
            )
        ] = selector({"location": {}})
    schema[
        vol.Required(
            CONF_SNOW_DEPTH_ENABLED,
            default=current.get(CONF_SNOW_DEPTH_ENABLED, DEFAULT_SNOW_DEPTH_ENABLED),
        )
    ] = cv.boolean
    if current.get(CONF_SNOW_DEPTH_STATION):
        schema[vol.Optional(CONF_SNOW_DEPTH_CHANGE_STATION, default=False)] = cv.boolean
    return schema


def _preserve_local_forecast_options(user_input, entry):
    """Keep each saved source's settings for older clients and when disabling it."""
    current = {**entry.data, **entry.options}
    user_input.setdefault(
        CONF_SNOW_DEPTH_ENABLED,
        current.get(CONF_SNOW_DEPTH_ENABLED, DEFAULT_SNOW_DEPTH_ENABLED),
    )
    for key in (CONF_SNOW_DEPTH_STATION, CONF_SNOW_DEPTH_PARAMETER):
        if key not in user_input and key in current:
            user_input[key] = current[key]
    for enabled_key, location_key, default in _LOCAL_FORECAST_OPTIONS:
        user_input.setdefault(enabled_key, current.get(enabled_key, default))
        if location_key not in user_input and location_key in current:
            user_input[location_key] = current[location_key]


def _build_entry_data(user_input, default_latitude, default_longitude):
    """Build persisted entry data without stale fields from another mode."""
    data = {
        CONF_MODE: user_input[CONF_MODE],
        CONF_LANGUAGE: user_input[CONF_LANGUAGE],
        CONF_INCLUDE_MESSAGES: user_input.get(
            CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES
        ),
        CONF_INCLUDE_GEOMETRY: user_input.get(
            CONF_INCLUDE_GEOMETRY, DEFAULT_INCLUDE_GEOMETRY
        ),
        CONF_MESSAGE_TYPES: user_input.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
        CONF_EXCLUDE_SEA: user_input.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA),
    }

    data[CONF_SNOW_DEPTH_ENABLED] = user_input.get(
        CONF_SNOW_DEPTH_ENABLED, DEFAULT_SNOW_DEPTH_ENABLED
    )
    if station := user_input.get(CONF_SNOW_DEPTH_STATION):
        data[CONF_SNOW_DEPTH_STATION] = station
        data[CONF_SNOW_DEPTH_PARAMETER] = user_input.get(
            CONF_SNOW_DEPTH_PARAMETER, DEFAULT_SNOW_DEPTH_PARAMETER
        )

    for enabled_key, location_key, default in _LOCAL_FORECAST_OPTIONS:
        data[enabled_key] = user_input.get(enabled_key, default)
        location = _forecast_location(user_input, enabled_key, location_key)
        if location is not None:
            data[location_key] = location

    if user_input[CONF_MODE] == "district":
        data[CONF_DISTRICT] = user_input[CONF_DISTRICT]
        return data

    location = _location_from_input(user_input, default_latitude, default_longitude)
    data[CONF_LOCATION] = location
    data[CONF_LATITUDE] = location["latitude"]
    data[CONF_LONGITUDE] = location["longitude"]
    data[CONF_RADIUS_KM] = user_input[CONF_RADIUS_KM]
    return data


async def _async_get_district_options(hass):
    """Fetch district options from SMHI metadata, with a static fallback."""
    district_options = []
    try:
        session = aiohttp_client.async_get_clientsession(hass)
        timeout = ClientTimeout(total=10)
        async with session.get(AREAS_URL, timeout=timeout) as resp:
            if resp.status == 200:
                areas = await resp.json()
                for area in areas:
                    area_id = str(area.get("id"))
                    label = area.get("sv") or area.get("en") or area_id
                    district_options.append({"label": label, "value": area_id})
    except Exception:
        district_options = []

    if not district_options:
        return [{"label": name, "value": number} for number, name in DISTRICTS.items()]

    if not any(item["value"] == "all" for item in district_options):
        district_options.append({"label": DISTRICTS["all"], "value": "all"})

    return sorted(
        district_options,
        key=lambda item: (item["value"] == "all", item["label"]),
    )


def _needs_snow_depth_selection(user_input, entry=None):
    """Only ask for a station when enabling or explicitly changing its source."""
    if not user_input.get(CONF_SNOW_DEPTH_ENABLED, DEFAULT_SNOW_DEPTH_ENABLED):
        return False
    current = {**entry.data, **entry.options} if entry else {}
    if (
        user_input.get(CONF_SNOW_DEPTH_CHANGE_STATION, False)
        or not current.get(CONF_SNOW_DEPTH_ENABLED, False)
        or not current.get(CONF_SNOW_DEPTH_STATION)
    ):
        return True
    return any(
        user_input.get(key) != current.get(key)
        for key in (CONF_SNOW_DEPTH_STATION, CONF_SNOW_DEPTH_PARAMETER)
    )


async def _async_get_snow_depth_stations(hass):
    """Discover source and station metadata only for an explicit selection."""
    from .snow_depth import async_get_snow_stations

    return await async_get_snow_stations(
        aiohttp_client.async_get_clientsession(hass),
        hass.config.latitude,
        hass.config.longitude,
    )


async def _async_validate_snow_depth_station(hass, station_id, parameter):
    """Probe only the selected source; catalogue availability is insufficient."""
    from .snow_depth import SmhiSnowDepthClient

    client = SmhiSnowDepthClient(
        aiohttp_client.async_get_clientsession(hass),
        station_id,
        parameter,
        latitude=hass.config.latitude,
        longitude=hass.config.longitude,
    )
    await client.async_get_observation(dt_util.utcnow())


class SnowDepthSelectionMixin:
    """Explicit station selection shared by setup, reconfigure and options."""

    async def _async_start_snow_depth_selection(self, data, finish):
        self._snow_depth_pending_data = dict(data)
        self._snow_depth_finish = finish
        self._snow_depth_stations = None
        return await self.async_step_snow_depth()

    async def async_step_snow_depth(self, user_input=None):
        errors = {}
        stations = self._snow_depth_stations
        if stations is None:
            try:
                stations = await _async_get_snow_depth_stations(self.hass)
            except (ClientError, TimeoutError, UpdateFailed, ValueError):
                errors["base"] = "cannot_connect_snow_depth"
            else:
                if stations:
                    self._snow_depth_stations = stations
                else:
                    errors["base"] = "no_snow_depth_stations"
        choices = {
            f"{station['parameter']}:{station['station_id']}": station
            for station in stations or []
        }
        if user_input is not None and choices and CONF_SNOW_DEPTH_STATION in user_input:
            selected = user_input.get(CONF_SNOW_DEPTH_STATION)
            if selected not in choices:
                errors[CONF_SNOW_DEPTH_STATION] = "invalid_snow_depth_station"
            else:
                station = choices[selected]
                try:
                    await _async_validate_snow_depth_station(
                        self.hass, station["station_id"], station["parameter"]
                    )
                except (ClientError, TimeoutError, UpdateFailed, ValueError):
                    errors[CONF_SNOW_DEPTH_STATION] = "snow_depth_station_unavailable"
                else:
                    data = dict(self._snow_depth_pending_data)
                    data[CONF_SNOW_DEPTH_STATION] = station["station_id"]
                    data[CONF_SNOW_DEPTH_PARAMETER] = station["parameter"]
                    return await self._snow_depth_finish(data)
        schema = {}
        if choices:
            options = []
            for value, station in choices.items():
                distance = station.get("distance_km")
                distance_label = (
                    f" · {distance:.1f} km"
                    if isinstance(distance, (int, float))
                    else ""
                )
                source_label = station.get("parameter_summary") or station["parameter"]
                options.append(
                    {
                        "value": value,
                        "label": f"{station['station_name']}{distance_label} · {source_label}",
                    }
                )
            pending = self._snow_depth_pending_data
            selected = f"{pending.get(CONF_SNOW_DEPTH_PARAMETER, DEFAULT_SNOW_DEPTH_PARAMETER)}:{pending.get(CONF_SNOW_DEPTH_STATION, '')}"
            description = {"suggested_value": selected} if selected in choices else {}
            schema[vol.Required(CONF_SNOW_DEPTH_STATION, description=description)] = (
                selector({"select": {"options": options, "mode": "dropdown"}})
            )
        return self.async_show_form(
            step_id="snow_depth", data_schema=vol.Schema(schema), errors=errors
        )


class SmhiAlertsConfigFlow(
    SnowDepthSelectionMixin, config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for SMHI Alerts."""

    VERSION = 4

    def __init__(self) -> None:
        self._pending_entry_title: str | None = None
        self._pending_entry_data: dict | None = None

    def _show_reload_notice_step(self, *, title: str, data: dict):
        """Store entry payload and show final reload notice step."""
        self._pending_entry_title = title
        self._pending_entry_data = data
        return self.async_show_form(step_id="reload_notice", data_schema=vol.Schema({}))

    async def async_step_reload_notice(self, user_input=None):
        """Final confirmation step before creating entry."""
        if user_input is None:
            return self.async_show_form(
                step_id="reload_notice", data_schema=vol.Schema({})
            )

        if self._pending_entry_title is None or self._pending_entry_data is None:
            return self.async_abort(reason="entry_not_found")

        title = self._pending_entry_title
        data = self._pending_entry_data
        self._pending_entry_title = None
        self._pending_entry_data = None
        return self.async_create_entry(title=title, data=data)

    async def _async_finish_reconfigure(self, new_data):
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
        if entry is None:
            return self.async_abort(reason="entry_not_found")
        if new_data[CONF_MODE] == "district":
            new_title = f"SMHI Alert ({DISTRICTS.get(new_data[CONF_DISTRICT], new_data[CONF_DISTRICT])})"
        else:
            new_title = f"SMHI Alert ({round(new_data[CONF_LATITUDE], 4)},{round(new_data[CONF_LONGITUDE], 4)} @ {new_data[CONF_RADIUS_KM]}km)"
        new_options = dict(new_data)
        new_options.pop(CONF_EXCLUDED_MESSAGE_TYPES, None)
        return self.async_update_reload_and_abort(
            entry=entry,
            data=new_data,
            options=new_options,
            reason="reconfigured_successful",
            title=new_title,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfigure initiated from the UI on an existing entry."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Build default values from current entry (options override data if set)
        current_mode = entry.options.get(
            CONF_MODE, entry.data.get(CONF_MODE, DEFAULT_MODE)
        )
        current_district = entry.options.get(
            CONF_DISTRICT, entry.data.get(CONF_DISTRICT, "all")
        )
        current_language = entry.options.get(
            CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        )
        current_include_messages = entry.options.get(
            CONF_INCLUDE_MESSAGES,
            entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
        )
        current_include_geometry = entry.options.get(
            CONF_INCLUDE_GEOMETRY,
            entry.data.get(CONF_INCLUDE_GEOMETRY, DEFAULT_INCLUDE_GEOMETRY),
        )
        current_lat = entry.options.get(
            CONF_LATITUDE, entry.data.get(CONF_LATITUDE, self.hass.config.latitude)
        )
        current_lon = entry.options.get(
            CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, self.hass.config.longitude)
        )
        current_location = entry.options.get(
            CONF_LOCATION,
            entry.data.get(
                CONF_LOCATION,
                {"latitude": current_lat, "longitude": current_lon},
            ),
        )
        current_radius = entry.options.get(
            CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
        )
        current_exclude_sea = entry.options.get(
            CONF_EXCLUDE_SEA,
            entry.data.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA),
        )
        current_message_types = _resolve_entry_message_types(entry)

        if user_input is not None:
            user_input = dict(user_input)
            _preserve_local_forecast_options(user_input, entry)
            errors = _local_forecast_errors(user_input)

        if user_input is not None and not errors:
            user_input.setdefault(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES)
            new_data = _build_entry_data(
                user_input, self.hass.config.latitude, self.hass.config.longitude
            )
            if _needs_snow_depth_selection(user_input, entry):
                return await self._async_start_snow_depth_selection(
                    new_data, self._async_finish_reconfigure
                )
            return await self._async_finish_reconfigure(new_data)

        district_options = await _async_get_district_options(self.hass)

        language_options = [
            {"label": name, "value": code} for code, name in LANGUAGE_OPTIONS.items()
        ]

        mode_options = [
            {"label": "District", "value": "district"},
            {"label": "Coordinate", "value": "coordinate"},
        ]

        message_options = _build_message_multiselect_options()

        # Conditional schema is not directly supported by selector, so we present all fields;
        # the coordinator will respect the selected mode and ignore the irrelevant ones.
        data_schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=current_mode): selector(
                    {"select": {"options": mode_options, "mode": "dropdown"}}
                ),
                vol.Optional(CONF_DISTRICT, default=current_district): selector(
                    {"select": {"options": district_options, "mode": "dropdown"}}
                ),
                vol.Optional(CONF_LOCATION, default=current_location): selector(
                    {"location": {}}
                ),
                vol.Optional(CONF_RADIUS_KM, default=current_radius): selector(
                    {
                        "number": {
                            "min": 1,
                            "max": 250,
                            "step": 1,
                            "unit_of_measurement": "km",
                        }
                    }
                ),
                vol.Required(CONF_LANGUAGE, default=current_language): selector(
                    {"select": {"options": language_options, "mode": "dropdown"}}
                ),
                vol.Required(
                    CONF_INCLUDE_MESSAGES, default=current_include_messages
                ): cv.boolean,
                vol.Required(
                    CONF_INCLUDE_GEOMETRY, default=current_include_geometry
                ): cv.boolean,
                vol.Required(CONF_EXCLUDE_SEA, default=current_exclude_sea): cv.boolean,
                vol.Optional(
                    CONF_MESSAGE_TYPES,
                    default=current_message_types,
                ): cv.multi_select(message_options),
            }
        )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                data_schema.extend(_local_forecast_schema(self.hass, entry)), user_input
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            user_input = dict(user_input)
            errors = _local_forecast_errors(user_input)

        if user_input is not None and not errors:
            mode = user_input[CONF_MODE]
            language = user_input[CONF_LANGUAGE]
            user_input.setdefault(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES)
            user_input.setdefault(CONF_INCLUDE_GEOMETRY, DEFAULT_INCLUDE_GEOMETRY)
            entry_data = _build_entry_data(
                user_input, self.hass.config.latitude, self.hass.config.longitude
            )
            if mode == "district":
                district = entry_data[CONF_DISTRICT]
                await self.async_set_unique_id(f"district:{district}:{language}")
                self._abort_if_unique_id_configured()
                title = f"SMHI Alert ({DISTRICTS.get(district, district)})"
            else:
                lat = entry_data[CONF_LATITUDE]
                lon = entry_data[CONF_LONGITUDE]
                radius = entry_data[CONF_RADIUS_KM]
                await self.async_set_unique_id(
                    f"coord:{round(lat, 4)},{round(lon, 4)}:{radius}:{language}"
                )
                self._abort_if_unique_id_configured()
                title = f"SMHI Alert ({round(lat, 4)},{round(lon, 4)} @ {radius}km)"
            if _needs_snow_depth_selection(user_input):
                self._pending_entry_title = title
                return await self._async_start_snow_depth_selection(
                    entry_data, self._async_finish_snow_depth_setup
                )
            return self._show_reload_notice_step(title=title, data=entry_data)

        district_options = await _async_get_district_options(self.hass)

        # Prepare language and mode options
        language_options = [
            {"label": name, "value": code} for code, name in LANGUAGE_OPTIONS.items()
        ]
        mode_options = [
            {"label": "District", "value": "district"},
            {"label": "Coordinate", "value": "coordinate"},
        ]

        message_options = _build_message_multiselect_options()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_MODE, default=DEFAULT_MODE): selector(
                    {"select": {"options": mode_options, "mode": "dropdown"}}
                ),
                vol.Optional(CONF_DISTRICT, default="all"): selector(
                    {
                        "select": {
                            "options": district_options,
                            "mode": "dropdown",
                        }
                    }
                ),
                vol.Optional(
                    CONF_LOCATION,
                    default={
                        "latitude": self.hass.config.latitude,
                        "longitude": self.hass.config.longitude,
                    },
                ): selector({"location": {}}),
                vol.Optional(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): selector(
                    {
                        "number": {
                            "min": 1,
                            "max": 250,
                            "step": 1,
                            "unit_of_measurement": "km",
                        }
                    }
                ),
                vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): selector(
                    {
                        "select": {
                            "options": language_options,
                            "mode": "dropdown",
                        }
                    }
                ),
                vol.Required(
                    CONF_INCLUDE_MESSAGES, default=DEFAULT_INCLUDE_MESSAGES
                ): cv.boolean,
                vol.Required(
                    CONF_INCLUDE_GEOMETRY, default=DEFAULT_INCLUDE_GEOMETRY
                ): cv.boolean,
                vol.Required(CONF_EXCLUDE_SEA, default=DEFAULT_EXCLUDE_SEA): cv.boolean,
                vol.Optional(
                    CONF_MESSAGE_TYPES,
                    default=DEFAULT_MESSAGE_TYPES,
                ): cv.multi_select(message_options),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                data_schema.extend(_local_forecast_schema(self.hass)), user_input
            ),
            errors=errors,
        )

    async def _async_finish_snow_depth_setup(self, data):
        return self._show_reload_notice_step(title=self._pending_entry_title, data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmhiAlertsOptionsFlowHandler()


class SmhiAlertsOptionsFlowHandler(SnowDepthSelectionMixin, config_entries.OptionsFlow):
    """Handle SMHI Alerts options."""

    async def _async_finish_snow_depth_options(self, data):
        return self.async_create_entry(title="", data=data)

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            user_input = dict(user_input)
            _preserve_local_forecast_options(user_input, self.config_entry)
            errors = _local_forecast_errors(user_input)

        if user_input is not None and not errors:
            user_input.setdefault(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES)
            user_input.setdefault(CONF_INCLUDE_GEOMETRY, DEFAULT_INCLUDE_GEOMETRY)
            data = _build_entry_data(
                user_input, self.hass.config.latitude, self.hass.config.longitude
            )
            if _needs_snow_depth_selection(user_input, self.config_entry):
                return await self._async_start_snow_depth_selection(
                    data, self._async_finish_snow_depth_options
                )
            return self.async_create_entry(title="", data=data)

        district_options = await _async_get_district_options(self.hass)

        language_options = [
            {"label": name, "value": code} for code, name in LANGUAGE_OPTIONS.items()
        ]
        mode_options = [
            {"label": "District", "value": "district"},
            {"label": "Coordinate", "value": "coordinate"},
        ]

        message_options = _build_message_multiselect_options()
        current_message_types = _resolve_entry_message_types(self.config_entry)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_MODE,
                    default=self.config_entry.options.get(
                        CONF_MODE,
                        self.config_entry.data.get(CONF_MODE, DEFAULT_MODE),
                    ),
                ): selector({"select": {"options": mode_options, "mode": "dropdown"}}),
                vol.Optional(
                    CONF_DISTRICT,
                    default=self.config_entry.options.get(
                        CONF_DISTRICT, self.config_entry.data.get(CONF_DISTRICT, "all")
                    ),
                ): selector(
                    {
                        "select": {
                            "options": district_options,
                            "mode": "dropdown",
                        }
                    }
                ),
                vol.Optional(
                    CONF_LOCATION,
                    default=self.config_entry.options.get(
                        CONF_LOCATION,
                        self.config_entry.data.get(
                            CONF_LOCATION,
                            {
                                "latitude": self.hass.config.latitude,
                                "longitude": self.hass.config.longitude,
                            },
                        ),
                    ),
                ): selector({"location": {}}),
                vol.Optional(
                    CONF_RADIUS_KM,
                    default=self.config_entry.options.get(
                        CONF_RADIUS_KM,
                        self.config_entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
                    ),
                ): selector(
                    {
                        "number": {
                            "min": 1,
                            "max": 250,
                            "step": 1,
                            "unit_of_measurement": "km",
                        }
                    }
                ),
                vol.Optional(
                    CONF_LANGUAGE,
                    default=self.config_entry.options.get(
                        CONF_LANGUAGE,
                        self.config_entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                    ),
                ): selector(
                    {
                        "select": {
                            "options": language_options,
                            "mode": "dropdown",
                        }
                    }
                ),
                vol.Optional(
                    CONF_INCLUDE_MESSAGES,
                    default=self.config_entry.options.get(
                        CONF_INCLUDE_MESSAGES,
                        self.config_entry.data.get(
                            CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES
                        ),
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_INCLUDE_GEOMETRY,
                    default=self.config_entry.options.get(
                        CONF_INCLUDE_GEOMETRY,
                        self.config_entry.data.get(
                            CONF_INCLUDE_GEOMETRY, DEFAULT_INCLUDE_GEOMETRY
                        ),
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_EXCLUDE_SEA,
                    default=self.config_entry.options.get(
                        CONF_EXCLUDE_SEA,
                        self.config_entry.data.get(
                            CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA
                        ),
                    ),
                ): cv.boolean,
                vol.Optional(
                    CONF_MESSAGE_TYPES,
                    default=current_message_types,
                ): cv.multi_select(message_options),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                data_schema.extend(
                    _local_forecast_schema(self.hass, self.config_entry)
                ),
                user_input,
            ),
            errors=errors,
        )
