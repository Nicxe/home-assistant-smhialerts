import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, CONF_DISTRICT, CONF_LANGUAGE, LANGUAGES, DEFAULT_DISTRICT, DEFAULT_LANGUAGE

class SmhiAlertConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SMHI Alert."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="SMHI Alert", data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_DISTRICT, default=DEFAULT_DISTRICT): str,
            vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): vol.In(LANGUAGES),
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SmhiAlertOptionsFlowHandler(config_entry)

class SmhiAlertOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_DISTRICT, default=self.config_entry.data.get(CONF_DISTRICT, DEFAULT_DISTRICT)): str,
            vol.Required(CONF_LANGUAGE, default=self.config_entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)): vol.In(LANGUAGES),
        })

        return self.async_show_form(step_id="init", data_schema=data_schema)
