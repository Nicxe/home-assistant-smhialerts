"""
Get weather alerts and warnings from SMHI.

Example configuration:

sensor:
  - platform: smhialert
    district: 'all'

Or specifying a specific district:

sensor:
  - platform: smhialert
    district: '19'
    language: 'sv'

Available districts: See README.md
"""

import logging
from datetime import timedelta

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import Throttle

__version__ = '1.0.5'

_LOGGER = logging.getLogger(__name__)

NAME = 'SMHIAlert'
CONF_DISTRICT = 'district'
CONF_LANGUAGE = 'language'

SCAN_INTERVAL = timedelta(minutes=5)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=NAME): cv.string,
    vol.Optional(CONF_DISTRICT, default='all'): cv.string,
    vol.Optional(CONF_LANGUAGE, default='en'): cv.string
})


async def async_setup_platform(hass: HomeAssistant, config, async_add_entities, discovery_info=None):
    """Set up the SMHI Alert sensor platform."""
    district = config.get(CONF_DISTRICT)
    language = config.get(CONF_LANGUAGE)
    name = config.get(CONF_NAME)
    session = async_get_clientsession(hass)
    api = SMHIAlert(district, language, session)

    async_add_entities([SMHIAlertSensor(api, name)], True)


class SMHIAlertSensor(SensorEntity):
    """Representation of the SMHI Alert sensor."""

    def __init__(self, api, name):
        self._api = api
        self._name = name
        self._icon = "mdi:alert"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def icon(self):
        """Return the sensor icon."""
        return self._icon

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._api.data.get('state')

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return self._api.attributes

    @property
    def available(self):
        """Return True if sensor is available."""
        return self._api.available

    async def async_update(self):
        """Fetch new state data for the sensor."""
        await self._api.async_update()


class SMHIAlert:
    """Class to handle data fetching from SMHI."""

    def __init__(self, district, language, session):
        self.district = district
        self.language = language
        self.session = session
        self.attributes = {
            "messages": [],
            "notice": ""
        }
        self.data = {
            'state': "No Alerts" if language == 'en' else "Inga varningar"
        }
        self.available = True

    @Throttle(SCAN_INTERVAL)
    async def async_update(self):
        """Fetch data from SMHI."""
        url = 'https://opendata-download-warnings.smhi.se/ibww/api/version/1/warning.json'
        try:
            async with async_timeout.timeout(10):
                async with self.session.get(url) as response:
                    if response.status != 200:
                        _LOGGER.error("Error fetching data from SMHI: %s", response.status)
                        self.available = False
                        return
                    data = await response.json()

            self._process_data(data)
            self.available = True
        except Exception as e:
            _LOGGER.error("Unable to fetch data from SMHI: %s", e)
            self.available = False

    def _process_data(self, data):
        """Process the data received from SMHI."""
        messages = []
        notice = ""

        # Reset state and attributes
        self.data['state'] = "No Alerts" if self.language == 'en' else "Inga varningar"
        self.attributes['messages'] = []
        self.attributes['notice'] = ""

        if not data:
            return

        for alert in data:
            event = alert.get('event', {}).get(self.language, '')
            warning_areas = alert.get('warningAreas', [])
            for area in warning_areas:
                affected_areas = area.get('affectedAreas', [])
                valid_areas = []

                for affected_area in affected_areas:
                    area_id = str(affected_area.get('id'))
                    area_name = affected_area.get(self.language)
                    if area_id == self.district or self.district == 'all':
                        valid_areas.append(area_name)

                if not valid_areas:
                    continue

                severity_info = area.get('warningLevel', {})
                code = severity_info.get('code', '').upper()
                severity = severity_info.get(self.language, '')
                level = severity

                descr = area.get('eventDescription', {}).get(self.language, '')
                start_time = area.get('approximateStart', '')
                end_time = area.get('approximateEnd', '')
                published = area.get('published', '')

                # Details
                details = ""
                descriptions = area.get('descriptions', [])
                for desc in descriptions:
                    title = desc.get('title', {}).get(self.language, '')
                    text = desc.get('text', {}).get(self.language, '')
                    details += f"{title}: {text}\n"

                msg = {
                    "event": event,
                    "start": start_time,
                    "end": end_time or ('Unknown' if self.language == 'en' else 'Okänt'),
                    "published": published,
                    "code": code,
                    "severity": severity,
                    "level": level,
                    "descr": descr,
                    "details": details,
                    "area": ", ".join(valid_areas),
                    "event_color": self._get_event_color(code)
                }

                messages.append(msg)
                notice += self._format_notice(msg)

        if messages:
            self.data['state'] = "Alert" if self.language == 'en' else "Varning"
            self.attributes['messages'] = messages
            self.attributes['notice'] = notice

    def _get_event_color(self, code):
        """Return color code based on severity code."""
        code_map = {
            "RED": "#FF0000",
            "ORANGE": "#FF7F00",
            "YELLOW": "#FFFF00"
        }
        return code_map.get(code, "#FFFFFF")

    def _format_notice(self, msg):
        """Format the notice string."""
        if self.language == 'en':
            return f"""[{msg["severity"]}] ({msg["published"]})
District: {msg["area"]}
Level: {msg["level"]}
Type: {msg["event"]}
Start: {msg["start"]}
End: {msg["end"]}
{msg["details"]}\n"""
        else:
            return f"""[{msg["severity"]}] ({msg["published"]})
Område: {msg["area"]}
Nivå: {msg["level"]}
Typ: {msg["event"]}
Start: {msg["start"]}
Slut: {msg["end"]}
Beskrivning:
{msg["details"]}\n"""
