"""Station-based SMHI snow depth observations, independent of forecasts."""

from datetime import UTC, datetime, timedelta
import logging
import math
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

SNOW_DEPTH_BASE_URL = "https://opendata-download-metobs.smhi.se/api/version/latest"
SNOW_DEPTH_UPDATE_INTERVAL = timedelta(minutes=30)
# Integration policy: allow daily 06 UTC observations plus 12 hours of delay.
# Catalogue wording does not establish a station's actual sampling cadence.
SNOW_DEPTH_MAX_AGE = timedelta(hours=36)
SNOW_DEPTH_FUTURE_TOLERANCE = timedelta(minutes=5)
SNOW_DEPTH_PARAMETERS = ("52", "8")


def _timestamp_ms(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _coordinate(value: Any, limit: int) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if math.isfinite(value) and -limit <= value <= limit:
            return float(value)
    except OverflowError:
        pass
    return None


def _distance(
    latitude: Any, longitude: Any, other_latitude: Any, other_longitude: Any
) -> float | None:
    lat = _coordinate(latitude, 90)
    lon = _coordinate(longitude, 180)
    other_lat = _coordinate(other_latitude, 90)
    other_lon = _coordinate(other_longitude, 180)
    if None in (lat, lon, other_lat, other_lon):
        return None
    a = (
        math.sin(math.radians(other_lat - lat) / 2) ** 2
        + math.cos(math.radians(lat))
        * math.cos(math.radians(other_lat))
        * math.sin(math.radians(other_lon - lon) / 2) ** 2
    )
    return round(6371 * 2 * math.asin(math.sqrt(min(1, max(0, a)))), 1)


def _source_url(station_id: str, parameter: str) -> str:
    return f"{SNOW_DEPTH_BASE_URL}/parameter/{parameter}/station/{station_id}/period/latest-day/data.json"


async def _async_json(session: ClientSession, url: str) -> dict[str, Any]:
    try:
        async with session.get(
            url, timeout=ClientTimeout(total=20), headers={"Accept": "application/json"}
        ) as response:
            if response.status != 200:
                raise UpdateFailed(f"Snow depth API returned HTTP {response.status}")
            payload = await response.json()
    except TimeoutError as err:
        raise UpdateFailed("Timed out fetching snow depth observations") from err
    except ClientError as err:
        raise UpdateFailed("Unable to fetch snow depth observations") from err
    except ValueError as err:
        raise UpdateFailed("Invalid snow depth JSON response") from err
    if not isinstance(payload, dict):
        raise UpdateFailed("Invalid snow depth response")
    return payload


async def async_get_snow_stations(
    session: ClientSession, latitude: float, longitude: float
) -> list[dict[str, Any]]:
    """List active station/source combinations without probing every station.

    Both catalogues may list the same manual stations. The chosen source must
    therefore be validated with an actual observation request during setup.
    """
    if _coordinate(latitude, 90) is None or _coordinate(longitude, 180) is None:
        raise ValueError("Invalid reference location")
    stations: dict[tuple[str, str], dict[str, Any]] = {}
    for parameter in SNOW_DEPTH_PARAMETERS:
        try:
            payload = await _async_json(
                session, f"{SNOW_DEPTH_BASE_URL}/parameter/{parameter}.json"
            )
        except UpdateFailed:
            continue
        if str(payload.get("key")) != parameter or not isinstance(
            payload.get("station"), list
        ):
            continue
        for row in payload["station"]:
            if not isinstance(row, dict) or row.get("active") is not True:
                continue
            station_id = str(row.get("key", ""))
            name = row.get("name")
            lat = _coordinate(row.get("latitude"), 90)
            lon = _coordinate(row.get("longitude"), 180)
            if (
                not station_id.isascii()
                or not station_id.isdigit()
                or not isinstance(name, str)
                or not name.strip()
                or lat is None
                or lon is None
            ):
                continue
            stations[(station_id, parameter)] = {
                "station_id": station_id,
                "station_name": name,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "distance_km": _distance(latitude, longitude, lat, lon),
                "parameter": parameter,
                "cadence": "minute" if parameter == "52" else "daily",
                "parameter_summary": payload.get("summary")
                if isinstance(payload.get("summary"), str)
                else parameter,
            }
    if not stations:
        raise UpdateFailed("No active snow depth stations available")
    return sorted(
        stations.values(),
        key=lambda row: (
            row["distance_km"],
            row["station_name"],
            SNOW_DEPTH_PARAMETERS.index(row["parameter"]),
        ),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def parse_snow_depth(
    payload: Any,
    station_id: str,
    parameter: str,
    now: datetime,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """Select the latest measurement, never a metadata publication timestamp."""
    if not isinstance(payload, dict):
        raise UpdateFailed("Invalid snow depth response")
    station = payload.get("station")
    source_parameter = payload.get("parameter")
    if not isinstance(station, dict) or str(station.get("key")) != station_id:
        raise UpdateFailed("Snow depth response does not match the selected station")
    if (
        not isinstance(source_parameter, dict)
        or str(source_parameter.get("key")) != parameter
        or source_parameter.get("unit") not in ("meter", "m")
    ):
        raise UpdateFailed("Snow depth response does not match the selected parameter")
    rows = payload.get("value")
    if not isinstance(rows, list):
        raise UpdateFailed("Invalid snow depth observations")
    dated = [
        (timestamp, row)
        for row in rows
        if isinstance(row, dict)
        and (timestamp := _timestamp_ms(row.get("date"))) is not None
    ]
    if not dated:
        raise UpdateFailed("No dated snow depth observation for the selected station")
    observed = max(timestamp for timestamp, _ in dated)
    if observed - now > SNOW_DEPTH_FUTURE_TOLERANCE:
        raise UpdateFailed("Snow depth observation time is in the future")
    latest = [row for timestamp, row in dated if timestamp == observed]
    values = {_number(row.get("value")) for row in latest}
    qualities = {
        row.get("quality") if isinstance(row.get("quality"), str) else None
        for row in latest
    }
    quality = next(iter(qualities)) if len(qualities) == 1 else "conflicting"
    raw = next(iter(values)) if len(values) == 1 else None
    cover = "trace" if raw == -0.01 else "patchy" if raw == -0.02 else None
    # Y covers both suspect and unchecked data. Preserve the flag, but do not
    # present those values as approved snow depth or replace them with zero.
    depth_cm = (
        round(raw * 100, 6)
        if raw is not None and 0 <= raw <= 3 and quality == "G"
        else None
    )
    station_latitude = None
    station_longitude = None
    positions = payload.get("position")
    if isinstance(positions, list):
        applicable = [
            row
            for row in positions
            if isinstance(row, dict)
            and (start := _timestamp_ms(row.get("from"))) is not None
            and (end := _timestamp_ms(row.get("to"))) is not None
            and start <= observed <= end
        ]
        if applicable:
            position = max(applicable, key=lambda row: row["from"])
            station_latitude = _coordinate(position.get("latitude"), 90)
            station_longitude = _coordinate(position.get("longitude"), 180)
    expires = observed + SNOW_DEPTH_MAX_AGE
    return {
        "source_kind": "snow_depth_observation",
        "station_id": station_id,
        "station_name": station.get("name")
        if isinstance(station.get("name"), str)
        else station_id,
        "station_latitude": station_latitude,
        "station_longitude": station_longitude,
        "distance_km": _distance(
            latitude, longitude, station_latitude, station_longitude
        ),
        "parameter": parameter,
        "source_url": _source_url(station_id, parameter),
        "observation_time": observed.isoformat(),
        "expires_at": expires.isoformat(),
        "stale": now >= expires,
        "quality": quality,
        "snow_cover": cover,
        "depth_cm": depth_cm if now < expires else None,
    }


class SmhiSnowDepthClient:
    """Read one explicitly selected station/source without silent fallback."""

    def __init__(
        self,
        session: ClientSession,
        station_id: str,
        parameter: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        if (
            not isinstance(station_id, str)
            or not station_id.isascii()
            or not station_id.isdigit()
            or parameter not in SNOW_DEPTH_PARAMETERS
        ):
            raise ValueError("Invalid snow depth station or parameter")
        self._session = session
        self.station_id = station_id
        self.parameter = parameter
        self._latitude = latitude
        self._longitude = longitude
        self.last_data: dict[str, Any] | None = None

    async def async_get_observation(self, now: datetime) -> dict[str, Any]:
        payload = await _async_json(
            self._session, _source_url(self.station_id, self.parameter)
        )
        data = parse_snow_depth(
            payload,
            self.station_id,
            self.parameter,
            now,
            latitude=self._latitude,
            longitude=self._longitude,
        )
        if (
            self.last_data
            and data["observation_time"] < self.last_data["observation_time"]
        ):
            raise UpdateFailed("Snow depth API returned an older observation")
        self.last_data = data
        if data["stale"]:
            raise UpdateFailed("Snow depth observation is stale")
        return data


class SmhiSnowDepthCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Keep observations optional and expire them independently of API polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        station_id: str,
        parameter: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        self._unsub_expiry: CALLBACK_TYPE | None = None
        super().__init__(
            hass,
            _LOGGER,
            name="observed snow depth",
            config_entry=entry,
            update_interval=SNOW_DEPTH_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = SmhiSnowDepthClient(
            aiohttp_client.async_get_clientsession(hass),
            station_id,
            parameter,
            latitude=latitude,
            longitude=longitude,
        )

    @property
    def observation_metadata(self) -> dict[str, Any]:
        """Keep station/time/quality available even while the source is down."""
        data = {
            "station_name": None,
            "station_latitude": None,
            "station_longitude": None,
            "distance_km": None,
            "observation_time": None,
            "expires_at": None,
            "quality": None,
            "snow_cover": None,
            "depth_cm": None,
            **(self._client.last_data or self.data or {}),
        }
        expires = data.get("expires_at")
        stale = bool(expires and dt_util.utcnow() >= datetime.fromisoformat(expires))
        data.update(
            {
                "source_kind": "snow_depth_observation",
                "station_id": self._client.station_id,
                "parameter": self._client.parameter,
                "source_url": _source_url(
                    self._client.station_id, self._client.parameter
                ),
                "stale": stale,
            }
        )
        if not self.last_update_success or stale:
            data["depth_cm"] = None
        return data

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._client.async_get_observation(dt_util.utcnow())
        expires = datetime.fromisoformat(data["expires_at"])
        if dt_util.utcnow() >= expires:
            raise UpdateFailed("Snow depth observation is stale")
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None
        if not self._shutdown_requested:
            self._unsub_expiry = async_track_point_in_utc_time(
                self.hass, self._async_expire, expires
            )
        return data

    @callback
    def _async_expire(self, now: datetime) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None
        if self._shutdown_requested or not self.last_update_success:
            return
        self.async_set_update_error(UpdateFailed("Snow depth observation is stale"))

    async def async_shutdown(self) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None
        await super().async_shutdown()
