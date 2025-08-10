import logging
import asyncio
from typing import Any, Dict, List, Tuple
from aiohttp import ClientError
import async_timeout
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.util import dt as dt_util
from .const import (
    DOMAIN,
    CONF_DISTRICT,
    CONF_LANGUAGE,
    CONF_INCLUDE_MESSAGES,
    DEFAULT_NAME,
    SCAN_INTERVAL,
    DISTRICTS,
    DEFAULT_LANGUAGE,
    DEFAULT_INCLUDE_MESSAGES,
    WARNINGS_URL,
    SEVERITY_ORDER,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up the sensor platform."""
    # Reuse coordinator created in __init__
    try:
        coordinator: SmhiAlertCoordinator = hass.data[DOMAIN][entry.entry_id][
            "coordinator"
        ]
    except KeyError:
        _LOGGER.error("Failed to fetch initial data: coordinator not initialized")
        return False

    sensor = SMHIAlertSensor(coordinator, entry)
    async_add_entities([sensor], True)

    return True


async def async_options_updated(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Options updated, refreshing coordinator")
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    # Update coordinator configuration
    coordinator.district = entry.options.get(
        CONF_DISTRICT, entry.data.get(CONF_DISTRICT, "all")
    )
    coordinator.language = entry.options.get(
        CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
    )
    coordinator.include_messages = entry.options.get(
        CONF_INCLUDE_MESSAGES,
        entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
    )
    await coordinator.async_request_refresh()


class SMHIAlertSensor(CoordinatorEntity, SensorEntity):
    """Representation of the SMHI Alert sensor."""

    def __init__(self, coordinator: "SmhiAlertCoordinator", entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.district = coordinator.district
        self.language = coordinator.language
        self._attr_name = (
            f"{DEFAULT_NAME} ({DISTRICTS.get(self.district, self.district)})"
        )
        self._attr_icon = "mdi:alert"
        self._attr_unique_id = f"{entry.entry_id}_smhi_alert_sensor_{self.district}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": self._attr_name,
            "manufacturer": "SMHI",
            "entry_type": DeviceEntryType.SERVICE,
        }

    @property
    def native_value(self):
        return self.coordinator.data.get("state")

    @property
    def extra_state_attributes(self):
        return self.coordinator.data.get("attributes")

    @property
    def name(self) -> str:
        # Reflect updated district name if options change
        return f"{DEFAULT_NAME} ({DISTRICTS.get(self.coordinator.district, self.coordinator.district)})"


class SmhiAlertCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from SMHI."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.district = entry.options.get(
            CONF_DISTRICT, entry.data.get(CONF_DISTRICT, "all")
        )
        self.language = entry.options.get(
            CONF_LANGUAGE, entry.data.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        )
        self.include_messages = entry.options.get(
            CONF_INCLUDE_MESSAGES,
            entry.data.get(CONF_INCLUDE_MESSAGES, DEFAULT_INCLUDE_MESSAGES),
        )
        self.session = aiohttp_client.async_get_clientsession(hass)
        self._etag: str | None = None
        self._last_modified: str | None = None
        self._last_success: str | None = None
        self._failure_count: int = 0
        self._base_interval = SCAN_INTERVAL

        super().__init__(
            hass,
            _LOGGER,
            name=f"SMHI Alert ({DISTRICTS.get(self.district, self.district)})",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from SMHI with conditional requests and build derived metrics."""
        headers: Dict[str, str] = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified

        data: Dict[str, Any] = {
            "state": "No Alerts" if self.language == "en" else "Inga varningar",
            "attributes": {
                "messages": [],
                "notice": "",
                "warnings_count": 0,
                "messages_count": 0,
                "alerts_count": 0,
                "highest_severity": "NONE",
                "attribution": "Data from SMHI",
                "last_update": None,
                "data_source_url": WARNINGS_URL,
            },
        }

        try:
            async with async_timeout.timeout(15):
                async with self.session.get(WARNINGS_URL, headers=headers) as response:
                    if response.status == 304:
                        # Not modified: just update timestamp
                        data.update(self.data or {})
                    else:
                        response.raise_for_status()
                        json_data = await response.json()
                        messages, notice, derived = self._process_data(json_data)
                        if derived["alerts_count"] > 0:
                            data["state"] = (
                                "Alert" if self.language == "en" else "Varning"
                            )
                        data["attributes"]["messages"] = messages
                        data["attributes"]["notice"] = notice
                        data["attributes"].update(derived)

                        # Save caching headers
                        self._etag = response.headers.get("ETag")
                        self._last_modified = response.headers.get("Last-Modified")

            self._last_success = dt_util.utcnow().isoformat()
            data["attributes"]["last_update"] = self._last_success
            # Localized timestamp
            try:
                data["attributes"]["last_update_local"] = dt_util.as_local(
                    dt_util.parse_datetime(self._last_success)
                ).isoformat()
            except Exception:
                data["attributes"]["last_update_local"] = None

            # Reset backoff on success
            self._failure_count = 0
            self.update_interval = self._base_interval
            return data

        except (ClientError, asyncio.TimeoutError) as err:
            # Exponential backoff
            self._failure_count += 1
            self._apply_backoff()
            raise UpdateFailed(f"Communication error: {err}") from err
        except ValueError as err:
            self._failure_count += 1
            self._apply_backoff()
            raise UpdateFailed(f"Invalid response: {err}") from err
        except Exception as err:
            self._failure_count += 1
            self._apply_backoff()
            raise UpdateFailed(str(err)) from err

    def _apply_backoff(self) -> None:
        # Cap backoff to 60 minutes
        factor = min(self._failure_count, 5)
        seconds = self._base_interval.total_seconds() * (2 ** factor)
        max_seconds = 60 * 60
        self.update_interval = dt_util.timedelta(seconds=min(seconds, max_seconds))

    def _process_data(self, data: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
        """Process data, compute derived metrics, and build messages and notice."""
        messages: List[Dict[str, Any]] = []
        notice_lines: List[str] = []
        highest_severity: str = "NONE"
        warnings_count = 0
        messages_count = 0

        if not data:
            return messages, "", {
                "warnings_count": 0,
                "messages_count": 0,
                "alerts_count": 0,
                "highest_severity": highest_severity,
            }

        for alert in data:
            event = alert.get("event", {}).get(self.language, "")
            warning_areas = alert.get("warningAreas", [])
            for area in warning_areas:
                affected_areas = area.get("affectedAreas", [])
                valid_areas: List[str] = []

                for affected_area in affected_areas:
                    area_id = str(affected_area.get("id"))
                    area_name = affected_area.get(self.language)
                    if area_id == self.district or self.district == "all":
                        if area_name:
                            valid_areas.append(area_name)

                if not valid_areas:
                    continue

                severity_info = area.get("warningLevel", {})
                code = str(severity_info.get("code", "")).upper()
                severity = severity_info.get(self.language, "") or code.title()

                if code == "MESSAGE" and not self.include_messages:
                    continue

                if code in ("YELLOW", "ORANGE", "RED"):
                    warnings_count += 1
                elif code == "MESSAGE":
                    messages_count += 1

                if SEVERITY_ORDER.index(code if code in SEVERITY_ORDER else "NONE") > SEVERITY_ORDER.index(highest_severity):
                    highest_severity = code

                descr = area.get("eventDescription", {}).get(self.language, "")
                start_time = area.get("approximateStart", "")
                end_time = area.get("approximateEnd", "") or (
                    "Unknown" if self.language == "en" else "Okänt"
                )
                published = area.get("published", "")

                # Local time conversions
                def to_local_iso(value: Any) -> Any:
                    if not isinstance(value, str):
                        return None
                    try:
                        dt_utc = dt_util.parse_datetime(value)
                        if dt_utc is None:
                            return None
                        return dt_util.as_local(dt_utc).isoformat()
                    except Exception:
                        return None

                start_local = to_local_iso(start_time)
                end_local = to_local_iso(end_time)
                published_local = to_local_iso(published)

                details_lines: List[str] = []
                descriptions = area.get("descriptions", [])
                for desc in descriptions:
                    title = desc.get("title", {}).get(self.language, "")
                    text = desc.get("text", {}).get(self.language, "")
                    if title or text:
                        details_lines.append(f"{title}: {text}".strip())
                details = "\n".join(details_lines)

                msg = {
                    "event": event,
                    "start": start_time,
                    "start_local": start_local,
                    "end": end_time,
                    "end_local": end_local,
                    "published": published,
                    "published_local": published_local,
                    "code": code,
                    "severity": severity,
                    "level": severity,
                    "descr": descr,
                    "details": details,
                    "area": ", ".join(valid_areas),
                    "event_color": self._get_event_color(code),
                }

                messages.append(msg)
                notice_lines.append(self._format_notice(msg))

        alerts_count = warnings_count + (messages_count if self.include_messages else 0)
        derived = {
            "warnings_count": warnings_count,
            "messages_count": messages_count,
            "alerts_count": alerts_count,
            "highest_severity": highest_severity,
        }
        return messages, "".join(notice_lines), derived

    def _get_event_color(self, code):
        """Return color code based on severity code."""
        code_map = {
            "RED": "#FF0000",
            "ORANGE": "#FF7F00",
            "YELLOW": "#FFFF00",
            "MESSAGE": "#FFFFFF",
        }
        return code_map.get(code, "#FFFFFF")

    def _format_notice(self, msg):
        """Format the notice string."""
        if self.language == "en":
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
