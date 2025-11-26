from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
from .const import (
    DOMAIN,
    DISTRICTS,
    CONF_DISTRICT,
    CONF_LANGUAGE,
    LANGUAGE_OPTIONS,
    DEFAULT_LANGUAGE,
    CONF_INCLUDE_MESSAGES,
    DEFAULT_INCLUDE_MESSAGES,
    AREAS_URL,
    CONF_MODE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_LOCATION,
    DEFAULT_MODE,
    DEFAULT_RADIUS_KM,
    CONF_EXCLUDE_SEA,
    DEFAULT_EXCLUDE_SEA,
    CONF_EXCLUDED_MESSAGE_TYPES,
    DEFAULT_EXCLUDED_MESSAGE_TYPES,
    CONF_MESSAGE_TYPES,
    DEFAULT_MESSAGE_TYPES,
    MESSAGE_EVENT_CATEGORIES,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import selector
from homeassistant.helpers import aiohttp_client


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


class SmhiAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMHI Alerts."""

    VERSION = 3

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfigure initiated from the UI on an existing entry."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Build default values from current entry (options override data if set)
        current_mode = entry.options.get(CONF_MODE, entry.data.get(CONF_MODE, DEFAULT_MODE))
        current_district = entry.options.get(CONF_DISTRICT, entry.data.get(CONF_DISTRICT, "all"))
        current_language = entry.options.get(CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))
        current_include_messages = entry.options.get(
            CONF_INCLUDE_MESSAGES,
            entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
        )
        current_lat = entry.options.get(CONF_LATITUDE, entry.data.get(CONF_LATITUDE, self.hass.config.latitude))
        current_lon = entry.options.get(CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, self.hass.config.longitude))
        current_location = entry.options.get(
            CONF_LOCATION,
            entry.data.get(
                CONF_LOCATION,
                {"latitude": current_lat, "longitude": current_lon},
            ),
        )
        current_radius = entry.options.get(CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM))
        current_exclude_sea = entry.options.get(
            CONF_EXCLUDE_SEA,
            entry.data.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA),
        )
        current_message_types = _resolve_entry_message_types(entry)

        if user_input is not None:
            user_input = dict(user_input)
            user_input.setdefault(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES)
            # Update entry data to reflect new baseline configuration
            new_data = {
                CONF_MODE: user_input[CONF_MODE],
                CONF_LANGUAGE: user_input[CONF_LANGUAGE],
                CONF_INCLUDE_MESSAGES: user_input.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
                CONF_MESSAGE_TYPES: user_input.get(
                    CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES
                ),
            }
            if user_input[CONF_MODE] == "district":
                new_data[CONF_DISTRICT] = user_input[CONF_DISTRICT]
                new_data[CONF_EXCLUDE_SEA] = user_input.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA)
                new_title = f"SMHI Alert ({DISTRICTS.get(new_data[CONF_DISTRICT], new_data[CONF_DISTRICT])})"
            else:
                # Map location selector to lat/lon plus radius
                loc = user_input.get(CONF_LOCATION) or {}
                new_data[CONF_LATITUDE] = loc.get("latitude", self.hass.config.latitude)
                new_data[CONF_LONGITUDE] = loc.get("longitude", self.hass.config.longitude)
                new_data[CONF_RADIUS_KM] = user_input[CONF_RADIUS_KM]
                new_data[CONF_EXCLUDE_SEA] = user_input.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA)
                new_title = f"SMHI Alert ({round(new_data[CONF_LATITUDE], 4)},{round(new_data[CONF_LONGITUDE], 4)} @ {new_data[CONF_RADIUS_KM]}km)"

            new_options = dict(entry.options)
            new_options[CONF_MESSAGE_TYPES] = new_data[CONF_MESSAGE_TYPES]
            new_options.pop(CONF_EXCLUDED_MESSAGE_TYPES, None)

            return self.async_update_reload_and_abort(
                entry=entry,
                data=new_data,
                options=new_options,
                reason="reconfigured_successful",
                title=new_title,
            )

        # Prepare dynamic district options (fallback to static)
        district_options = []
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(AREAS_URL, timeout=10) as resp:
                if resp.status == 200:
                    areas = await resp.json()
                    for area in areas:
                        area_id = str(area.get("id"))
                        label = area.get("sv") or area.get("en") or area_id
                        district_options.append({"label": label, "value": area_id})
        except Exception:
            district_options = []
        if not district_options:
            district_options = [
                {"label": name, "value": number} for number, name in DISTRICTS.items()
            ]

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
                vol.Optional(CONF_LOCATION, default=current_location): selector({"location": {}}),
                vol.Optional(CONF_RADIUS_KM, default=current_radius): selector({"number": {"min": 1, "max": 250, "step": 1, "unit_of_measurement": "km"}}),
                vol.Required(CONF_LANGUAGE, default=current_language): selector(
                    {"select": {"options": language_options, "mode": "dropdown"}}
                ),
                vol.Required(CONF_INCLUDE_MESSAGES, default=current_include_messages): cv.boolean,
                vol.Required(CONF_EXCLUDE_SEA, default=current_exclude_sea): cv.boolean,
                vol.Optional(
                    CONF_MESSAGE_TYPES,
                    default=current_message_types,
                ): cv.multi_select(message_options),
            }
        )

        return self.async_show_form(step_id="reconfigure", data_schema=data_schema, errors=errors)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            mode = user_input[CONF_MODE]
            language = user_input[CONF_LANGUAGE]
            user_input.setdefault(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES)
            if mode == "district":
                district = user_input[CONF_DISTRICT]
                await self.async_set_unique_id(f"district:{district}:{language}")
                self._abort_if_unique_id_configured()
                title = f"SMHI Alert ({DISTRICTS.get(district, district)})"
            else:
                loc = user_input.get(CONF_LOCATION) or {}
                lat = loc.get("latitude", self.hass.config.latitude)
                lon = loc.get("longitude", self.hass.config.longitude)
                radius = user_input.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
                await self.async_set_unique_id(f"coord:{round(lat,4)},{round(lon,4)}:{radius}:{language}")
                self._abort_if_unique_id_configured()
                title = f"SMHI Alert ({round(lat, 4)},{round(lon, 4)} @ {radius}km)"
            return self.async_create_entry(
                title=title,
                data=user_input,
            )

        # Try fetch dynamic areas list; fallback to static
        district_options = []
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(AREAS_URL, timeout=10) as resp:
                if resp.status == 200:
                    areas = await resp.json()
                    # Expecting list of { id, sv, en }
                    for area in areas:
                        area_id = str(area.get("id"))
                        label = area.get("sv") or area.get("en") or area_id
                        district_options.append({"label": label, "value": area_id})
        except Exception:
            district_options = []
        if not district_options:
            district_options = [
                {"label": name, "value": number} for number, name in DISTRICTS.items()
            ]

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
                vol.Optional(CONF_LOCATION, default={"latitude": self.hass.config.latitude, "longitude": self.hass.config.longitude}): selector({"location": {}}),
                vol.Optional(CONF_RADIUS_KM, default=DEFAULT_RADIUS_KM): selector({"number": {"min": 1, "max": 250, "step": 1, "unit_of_measurement": "km"}}),
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
                vol.Required(CONF_EXCLUDE_SEA, default=DEFAULT_EXCLUDE_SEA): cv.boolean,
                vol.Optional(
                    CONF_MESSAGE_TYPES,
                    default=DEFAULT_MESSAGE_TYPES,
                ): cv.multi_select(message_options),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmhiAlertsOptionsFlowHandler()


class SmhiAlertsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle SMHI Alerts options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            user_input = dict(user_input)
            user_input.setdefault(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES)
            # Map location into latitude/longitude for coordinator consumption
            data = dict(self.config_entry.options)
            data.update(user_input)
            if CONF_LOCATION in user_input:
                loc = user_input.get(CONF_LOCATION) or {}
                data[CONF_LATITUDE] = loc.get("latitude", self.hass.config.latitude)
                data[CONF_LONGITUDE] = loc.get("longitude", self.hass.config.longitude)
            return self.async_create_entry(title="", data=data)

        # Try dynamic areas again, fallback to static
        district_options = []
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(AREAS_URL, timeout=10) as resp:
                if resp.status == 200:
                    areas = await resp.json()
                    for area in areas:
                        area_id = str(area.get("id"))
                        label = area.get("sv") or area.get("en") or area_id
                        district_options.append({"label": label, "value": area_id})
        except Exception:
            district_options = []
        if not district_options:
            district_options = [
                {"label": name, "value": number} for number, name in DISTRICTS.items()
            ]

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
                            {"latitude": self.hass.config.latitude, "longitude": self.hass.config.longitude},
                        ),
                    ),
                ): selector({"location": {}}),
                vol.Optional(
                    CONF_RADIUS_KM,
                    default=self.config_entry.options.get(
                        CONF_RADIUS_KM,
                        self.config_entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM),
                    ),
                ): selector({"number": {"min": 1, "max": 250, "step": 1, "unit_of_measurement": "km"}}),
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
                    CONF_EXCLUDE_SEA,
                    default=self.config_entry.options.get(
                        CONF_EXCLUDE_SEA,
                        self.config_entry.data.get(CONF_EXCLUDE_SEA, DEFAULT_EXCLUDE_SEA),
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
            data_schema=data_schema,
            errors=errors,
        )
