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
)
from homeassistant.helpers.selector import selector
import homeassistant.helpers.config_validation as cv

class SmhiAlertsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMHI Alerts."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            district = user_input[CONF_DISTRICT]

            # Tillåt flera instanser utan unika ID
            return self.async_create_entry(title=f"SMHI Alert ({DISTRICTS.get(district, district)})", data=user_input)

        # Förbered val för distrikt
        district_options = [
            {"label": name, "value": number} for number, name in DISTRICTS.items()
        ]

        # Förbered val för språk
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
                vol.Required(CONF_INCLUDE_MESSAGES, default=DEFAULT_INCLUDE_MESSAGES): cv.boolean,
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
        return SmhiAlertsOptionsFlowHandler

class SmhiAlertsOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle SMHI Alerts options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

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
                        CONF_LANGUAGE, self.config_entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
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
                        self.config_entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
                    ),
                ): cv.boolean,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )
