import logging
import asyncio
import unicodedata
from typing import Any, Dict, List, Tuple, Optional
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
    CONF_MODE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_KM,
    CONF_EXCLUDE_SEA,
    CONF_EXCLUDED_MESSAGE_TYPES,
    CONF_MESSAGE_TYPES,
    DEFAULT_NAME,
    SCAN_INTERVAL,
    DISTRICTS,
    DEFAULT_LANGUAGE,
    DEFAULT_INCLUDE_MESSAGES,
    DEFAULT_MODE,
    DEFAULT_RADIUS_KM,
    DEFAULT_EXCLUDED_MESSAGE_TYPES,
    DEFAULT_MESSAGE_TYPES,
    WARNINGS_URL,
    SEVERITY_ORDER,
    MARINE_AREA_IDS,
    MARINE_EVENT_CODES,
    MESSAGE_EVENT_DEFINITIONS,
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
    coordinator.mode = entry.options.get(
        CONF_MODE, entry.data.get(CONF_MODE, DEFAULT_MODE)
    )
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
    coordinator.set_message_types(
        entry.options.get(
            CONF_MESSAGE_TYPES,
            entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
        ),
        entry.options.get(
            CONF_EXCLUDED_MESSAGE_TYPES,
            entry.data.get(CONF_EXCLUDED_MESSAGE_TYPES, DEFAULT_EXCLUDED_MESSAGE_TYPES),
        ),
    )
    coordinator.exclude_sea = entry.options.get(
        CONF_EXCLUDE_SEA,
        entry.data.get(CONF_EXCLUDE_SEA, False),
    )
    coordinator.latitude = float(
        entry.options.get(
            CONF_LATITUDE, entry.data.get(CONF_LATITUDE, hass.config.latitude)
        )
    )
    coordinator.longitude = float(
        entry.options.get(
            CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, hass.config.longitude)
        )
    )
    coordinator.radius_km = float(
        entry.options.get(
            CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
        )
    )
    await coordinator.async_request_refresh()


class SMHIAlertSensor(CoordinatorEntity, SensorEntity):
    """Representation of the SMHI Alert sensor."""

    def __init__(self, coordinator: "SmhiAlertCoordinator", entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.district = coordinator.district
        self.language = coordinator.language
        self._attr_name = self._derive_name()
        self._attr_icon = "mdi:alert"
        self._attr_unique_id = self._derive_unique_id()
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": self._attr_name,
            "manufacturer": "Nicxe",
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
        return self._derive_name()

    def _derive_name(self) -> str:
        if getattr(self.coordinator, "mode", DEFAULT_MODE) == "coordinate":
            lat = round(getattr(self.coordinator, "latitude", 0.0), 4)
            lon = round(getattr(self.coordinator, "longitude", 0.0), 4)
            r = int(round(getattr(self.coordinator, "radius_km", DEFAULT_RADIUS_KM)))
            return f"{DEFAULT_NAME} ({lat},{lon} @ {r}km)"
        else:
            district = getattr(self.coordinator, "district", "all")
            return f"{DEFAULT_NAME} ({DISTRICTS.get(district, district)})"

    def _derive_unique_id(self) -> str:
        if getattr(self.coordinator, "mode", DEFAULT_MODE) == "coordinate":
            lat = round(getattr(self.coordinator, "latitude", 0.0), 4)
            lon = round(getattr(self.coordinator, "longitude", 0.0), 4)
            r = int(round(getattr(self.coordinator, "radius_km", DEFAULT_RADIUS_KM)))
            return f"{self.entry.entry_id}_smhi_alert_sensor_coord_{lat}_{lon}_{r}km"
        else:
            return f"{self.entry.entry_id}_smhi_alert_sensor_{self.coordinator.district}"


class SmhiAlertCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from SMHI."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.mode = entry.options.get(
            CONF_MODE, entry.data.get(CONF_MODE, DEFAULT_MODE)
        )
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
        self.exclude_sea = entry.options.get(
            CONF_EXCLUDE_SEA,
            entry.data.get(CONF_EXCLUDE_SEA, False),
        )
        self.latitude = float(
            entry.options.get(
                CONF_LATITUDE, entry.data.get(CONF_LATITUDE, hass.config.latitude)
            )
        )
        self.longitude = float(
            entry.options.get(
                CONF_LONGITUDE, entry.data.get(CONF_LONGITUDE, hass.config.longitude)
            )
        )
        self.radius_km = float(
            entry.options.get(
                CONF_RADIUS_KM, entry.data.get(CONF_RADIUS_KM, DEFAULT_RADIUS_KM)
            )
        )
        self.session = aiohttp_client.async_get_clientsession(hass)
        self.message_types: List[str] = []
        self._allowed_message_tokens: set[str] = set()
        self.set_message_types(
            entry.options.get(
                CONF_MESSAGE_TYPES,
                entry.data.get(CONF_MESSAGE_TYPES, DEFAULT_MESSAGE_TYPES),
            ),
            entry.options.get(
                CONF_EXCLUDED_MESSAGE_TYPES,
                entry.data.get(CONF_EXCLUDED_MESSAGE_TYPES, DEFAULT_EXCLUDED_MESSAGE_TYPES),
            ),
        )
        self._etag: str | None = None
        self._last_modified: str | None = None
        self._last_success: str | None = None
        self._failure_count: int = 0
        self._base_interval = SCAN_INTERVAL

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DEFAULT_NAME} ({DISTRICTS.get(self.district, self.district)})",
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )

    def set_message_types(
        self,
        values: Optional[List[str]],
        legacy_excluded: Optional[List[str]] = None,
    ) -> None:
        """Update allowed message categories."""
        allowed = self._normalize_message_types(values, legacy_excluded)
        self.message_types = allowed
        self._rebuild_allowed_message_tokens()

    def _normalize_message_types(
        self,
        values: Optional[List[str]],
        legacy_excluded: Optional[List[str]],
    ) -> List[str]:
        if isinstance(values, list) and values:
            selected = [v for v in values if v in MESSAGE_EVENT_DEFINITIONS]
        else:
            selected = []
        if not selected and legacy_excluded:
            selected = [
                code for code in DEFAULT_MESSAGE_TYPES if code not in set(legacy_excluded)
            ]
        if not selected:
            selected = list(DEFAULT_MESSAGE_TYPES)
        # Preserve order defined in DEFAULT_MESSAGE_TYPES
        order = {code: idx for idx, code in enumerate(DEFAULT_MESSAGE_TYPES)}
        return sorted(set(selected), key=lambda code: order.get(code, 0))

    def _normalize_message_token(self, value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        decomposed = unicodedata.normalize("NFKD", value)
        stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
        return "".join(ch for ch in stripped.upper() if ch.isalnum())

    def _rebuild_allowed_message_tokens(self) -> None:
        tokens: set[str] = set()
        for code in self.message_types or []:
            definition = MESSAGE_EVENT_DEFINITIONS.get(code)
            if not definition:
                continue
            for candidate in [definition["value"], *definition.get("aliases", [])]:
                token = self._normalize_message_token(candidate)
                if token:
                    tokens.add(token)
        self._allowed_message_tokens = tokens

    def _should_include_message(self, event_obj: Dict[str, Any]) -> bool:
        if not self._allowed_message_tokens:
            return False
        candidates: List[str] = []
        code = event_obj.get("code")
        if isinstance(code, str):
            candidates.append(code)
        for key in ("sv", "en"):
            value = event_obj.get(key)
            if isinstance(value, str):
                candidates.append(value)
        mho_code = (event_obj.get("mhoClassification") or {}).get("code")
        if isinstance(mho_code, str):
            candidates.append(mho_code)
        for candidate in candidates:
            if self._normalize_message_token(candidate) in self._allowed_message_tokens:
                return True
        return False

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
                "filter_mode": getattr(self, "mode", DEFAULT_MODE),
                "filter_latitude": getattr(self, "latitude", None),
                "filter_longitude": getattr(self, "longitude", None),
                "filter_radius_km": getattr(self, "radius_km", None),
                "filter_exclude_sea": getattr(self, "exclude_sea", False),
                "filter_message_types": list(
                    getattr(self, "message_types", DEFAULT_MESSAGE_TYPES)
                    or DEFAULT_MESSAGE_TYPES
                ),
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
                        data["attributes"]["filter_message_types"] = list(
                            self.message_types or DEFAULT_MESSAGE_TYPES
                        )

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
            data["attributes"]["filter_message_types"] = list(
                self.message_types or DEFAULT_MESSAGE_TYPES
            )

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
            event_obj = alert.get("event", {})
            event_code = str(event_obj.get("code", "")).upper()
            mho_class = (event_obj.get("mhoClassification", {}) or {}).get("code")
            mho_class = str(mho_class).upper() if mho_class else None
            warning_areas = alert.get("warningAreas", [])
            for area in warning_areas:
                valid_areas: List[str] = []

                if getattr(self, "mode", DEFAULT_MODE) == "coordinate":
                    if self.exclude_sea and self._is_marine_area(area, event_code, mho_class):
                        continue
                    if self._area_matches_coordinate_filter(area):
                        name_obj = area.get("areaName", {})
                        label = name_obj.get(self.language) or name_obj.get("en") or name_obj.get("sv")
                        if label:
                            valid_areas.append(label)
                        else:
                            valid_areas.append("Area")
                    else:
                        continue
                else:
                    affected_areas = area.get("affectedAreas", [])
                    for affected_area in affected_areas:
                        area_id = str(affected_area.get("id"))
                        area_name = affected_area.get(self.language)
                        if self.exclude_sea and (area_id in MARINE_AREA_IDS or event_code in MARINE_EVENT_CODES or mho_class == "OCE" or event_code.endswith("_SEA")):
                            continue
                        if area_id == self.district or self.district == "all":
                            if area_name:
                                valid_areas.append(area_name)
                    if not valid_areas:
                        continue

                severity_info = area.get("warningLevel", {})
                code = str(severity_info.get("code", "")).upper()
                severity = severity_info.get(self.language, "") or code.title()

                if code == "MESSAGE":
                    if not self.include_messages:
                        continue
                    if not self._should_include_message(event_obj):
                        continue
                    messages_count += 1
                elif code in ("YELLOW", "ORANGE", "RED"):
                    warnings_count += 1

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

        # Sort messages by severity (most severe first): RED > ORANGE > YELLOW > MESSAGE
        def _rank(code: str) -> int:
            return SEVERITY_ORDER.index(code if code in SEVERITY_ORDER else "NONE")

        messages_sorted = sorted(messages, key=lambda m: _rank(m.get("code", "NONE")), reverse=True)
        # Rebuild notice to reflect sorted order
        notice_sorted = "".join(self._format_notice(m) for m in messages_sorted)
        return messages_sorted, notice_sorted, derived

    # --- Geometry helpers for coordinate filtering ---
    def _area_matches_coordinate_filter(self, area: Dict[str, Any]) -> bool:
        geometry_container = area.get("area")
        if not geometry_container:
            return False

        center_lon = float(getattr(self, "longitude", 0.0))
        center_lat = float(getattr(self, "latitude", 0.0))
        radius_m = float(getattr(self, "radius_km", DEFAULT_RADIUS_KM)) * 1000.0

        def feature_matches(feature: Dict[str, Any]) -> bool:
            geom = feature.get("geometry", feature)  # feature or raw geometry
            if not isinstance(geom, dict):
                return False
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            if not gtype or coords is None:
                return False
            if gtype == "Polygon":
                return self._polygon_within_radius(center_lon, center_lat, radius_m, coords)
            if gtype == "LineString":
                return self._linestring_within_radius(center_lon, center_lat, radius_m, coords)
            if gtype == "MultiPolygon":
                for poly in coords or []:
                    if self._polygon_within_radius(center_lon, center_lat, radius_m, poly):
                        return True
                return False
            if gtype == "MultiLineString":
                for line in coords or []:
                    if self._linestring_within_radius(center_lon, center_lat, radius_m, line):
                        return True
                return False
            return False

        gtype = geometry_container.get("type")
        if gtype == "FeatureCollection":
            for feat in geometry_container.get("features", []) or []:
                if feature_matches(feat):
                    return True
            return False
        if gtype == "Feature":
            return feature_matches(geometry_container)
        # Some payloads embed raw geometry directly
        return feature_matches(geometry_container)

    def _is_marine_area(self, area: Dict[str, Any], event_code: str, mho_class: Optional[str]) -> bool:
        # Marine by event classification
        if event_code in MARINE_EVENT_CODES or (event_code and event_code.endswith("_SEA")):
            return True
        if mho_class == "OCE":
            return True
        # Marine by affectedAreas IDs
        for affected in area.get("affectedAreas", []) or []:
            if str(affected.get("id")) in MARINE_AREA_IDS:
                return True
        return False

    def _project(self, lon: float, lat: float, lon0: float, lat0: float) -> Tuple[float, float]:
        # Equirectangular projection around (lon0, lat0) in meters
        from math import radians, cos

        R = 6371000.0
        lat_r = radians(lat)
        lon_r = radians(lon)
        lat0_r = radians(lat0)
        lon0_r = radians(lon0)
        x = (lon_r - lon0_r) * cos(lat0_r) * R
        y = (lat_r - lat0_r) * R
        return x, y

    def _point_in_polygon(self, point_xy: Tuple[float, float], poly_lonlat_rings: List[List[List[float]]], center_lon: float, center_lat: float) -> bool:
        # Only consider outer ring for inclusion; ignore holes for simplicity
        if not poly_lonlat_rings:
            return False
        outer = poly_lonlat_rings[0]
        if not outer:
            return False
        x, y = point_xy
        inside = False
        # Ray casting
        prev_x = prev_y = None
        for i in range(len(outer)):
            lon_i, lat_i = outer[i]
            lon_j, lat_j = outer[i - 1] if i > 0 else outer[-1]
            xi, yi = self._project(lon_i, lat_i, center_lon, center_lat)
            xj, yj = self._project(lon_j, lat_j, center_lon, center_lat)
            intersect = ((yi > y) != (yj > y)) and (
                x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
            )
            if intersect:
                inside = not inside
        return inside

    def _distance_point_to_segment(self, px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        # Return min distance from point P to segment AB in meters
        from math import hypot

        abx = bx - ax
        aby = by - ay
        apx = px - ax
        apy = py - ay
        denom = abx * abx + aby * aby
        if denom <= 0:
            return hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
        cx = ax + t * abx
        cy = ay + t * aby
        return hypot(px - cx, py - cy)

    def _polygon_within_radius(self, center_lon: float, center_lat: float, radius_m: float, poly_coords: List[List[List[float]]]) -> bool:
        px, py = self._project(center_lon, center_lat, center_lon, center_lat)
        if self._point_in_polygon((px, py), poly_coords, center_lon, center_lat):
            return True
        # Min distance to outer ring
        outer = poly_coords[0] if poly_coords else []
        if len(outer) < 2:
            return False
        min_d = 1e20
        prev = None
        for pt in outer:
            if prev is None:
                prev = pt
                continue
            ax, ay = self._project(prev[0], prev[1], center_lon, center_lat)
            bx, by = self._project(pt[0], pt[1], center_lon, center_lat)
            d = self._distance_point_to_segment(px, py, ax, ay, bx, by)
            if d < min_d:
                min_d = d
            prev = pt
        # Close ring
        ax, ay = self._project(outer[-1][0], outer[-1][1], center_lon, center_lat)
        bx, by = self._project(outer[0][0], outer[0][1], center_lon, center_lat)
        d = self._distance_point_to_segment(px, py, ax, ay, bx, by)
        if d < min_d:
            min_d = d
        return min_d <= radius_m

    def _linestring_within_radius(self, center_lon: float, center_lat: float, radius_m: float, line_coords: List[List[float]]) -> bool:
        if not line_coords or len(line_coords) < 2:
            return False
        px, py = self._project(center_lon, center_lat, center_lon, center_lat)
        min_d = 1e20
        prev = None
        for pt in line_coords:
            if prev is None:
                prev = pt
                continue
            ax, ay = self._project(prev[0], prev[1], center_lon, center_lat)
            bx, by = self._project(pt[0], pt[1], center_lon, center_lat)
            d = self._distance_point_to_segment(px, py, ax, ay, bx, by)
            if d < min_d:
                min_d = d
            prev = pt
        return min_d <= radius_m

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
