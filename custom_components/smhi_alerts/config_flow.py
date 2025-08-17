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
)
from homeassistant.helpers.selector import selector
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import aiohttp_client


class SmhiAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMHI Alerts."""

    VERSION = 1

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfigure initiated from the UI on an existing entry."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context.get("entry_id"))
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        # Build default values from current entry (options override data if set)
        current_district = entry.options.get(CONF_DISTRICT, entry.data.get(CONF_DISTRICT, "all"))
        current_language = entry.options.get(CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))
        current_include_messages = entry.options.get(
            CONF_INCLUDE_MESSAGES,
            entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
        )

        if user_input is not None:
            # Update entry data to reflect new baseline configuration
            new_data = {
                CONF_DISTRICT: user_input[CONF_DISTRICT],
                CONF_LANGUAGE: user_input[CONF_LANGUAGE],
                CONF_INCLUDE_MESSAGES: user_input.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
            }
            new_title = f"SMHI Alert ({DISTRICTS.get(new_data[CONF_DISTRICT], new_data[CONF_DISTRICT])})"

            return self.async_update_reload_and_abort(
                entry=entry,
                data=new_data,
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

        data_schema = vol.Schema(
            {
                vol.Required(CONF_DISTRICT, default=current_district): selector(
                    {"select": {"options": district_options, "mode": "dropdown"}}
                ),
                vol.Required(CONF_LANGUAGE, default=current_language): selector(
                    {"select": {"options": language_options, "mode": "dropdown"}}
                ),
                vol.Required(CONF_INCLUDE_MESSAGES, default=current_include_messages): cv.boolean,
            }
        )

        return self.async_show_form(step_id="reconfigure", data_schema=data_schema, errors=errors)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            district = user_input[CONF_DISTRICT]
            language = user_input[CONF_LANGUAGE]
            # unique per district+language
            await self.async_set_unique_id(f"{district}:{language}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"SMHI Alert ({DISTRICTS.get(district, district)})",
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

        # Prepare language options
        language_options = [
            {"label": name, "value": code} for code, name in LANGUAGE_OPTIONS.items()
        ]

        data_schema = vol.Schema(
            {
                vol.Required(CONF_DISTRICT, default="all"): selector(
                    {
                        "select": {
                            "options": district_options,
                            "mode": "dropdown",
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
            return self.async_create_entry(title="", data=user_input)

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

        data_schema = vol.Schema(
            {
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
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )
