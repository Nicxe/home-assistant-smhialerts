"""Local thunderstorm probabilities from SMHI SNOW point forecasts."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import logging
import math
from typing import Any, TypedDict

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

THUNDER_BASE_URL = (
    "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
)
THUNDER_CREATED_TIME_URL = f"{THUNDER_BASE_URL}/createdtime.json"
THUNDER_UPDATE_INTERVAL = timedelta(minutes=15)
# SNOW is updated four times per hour. Eight missed updates expires the source.
THUNDER_MAX_AGE = timedelta(hours=2)
THUNDER_FUTURE_TOLERANCE = timedelta(minutes=15)
THUNDER_FORECAST_WINDOW = timedelta(hours=48)


class ThunderForecastPoint(TypedDict):
    """Probability at one actual SMHI valid time, not a period total."""

    valid_time: str
    probability: float | int | None


class ThunderData(TypedDict):
    """Source metadata, next forecast time and a bounded future time series."""

    created_time: str
    reference_time: str | None
    current: ThunderForecastPoint | None
    forecast: list[ThunderForecastPoint]
    grid_latitude: float | None
    grid_longitude: float | None
    data_source_url: str
    source_kind: str
    probability_unit: str


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _probability(value: Any) -> float | int | None:
    """SNOW provides percent already; 9999 and malformed values are unknown."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 100
    ):
        return None
    return value


def _grid_point(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None, None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return None, None
    longitude, latitude = coordinates
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in coordinates
    ) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None, None
    return float(latitude), float(longitude)


def parse_thunder(payload: Any, now: datetime) -> ThunderData:
    """Select the nearest strictly future forecast time without interpolation.

    SNOW documents non-precipitation parameters as instantaneous at ``time``.
    ``intervalParametersStartTime`` is therefore not a thunder probability
    interval. Unknown values at the next timestamp must remain unknown even
    when a later timestamp has a usable value.
    """
    if not isinstance(payload, dict):
        raise UpdateFailed("Invalid thunderstorm forecast response")
    created = _timestamp(payload.get("createdTime"))
    if created is None:
        raise UpdateFailed("Missing or invalid thunderstorm forecast creation time")
    if now - created >= THUNDER_MAX_AGE:
        raise UpdateFailed("Thunderstorm forecast is stale")
    if created - now > THUNDER_FUTURE_TOLERANCE:
        raise UpdateFailed("Thunderstorm forecast creation time is in the future")
    time_series = payload.get("timeSeries")
    if not isinstance(time_series, list):
        raise UpdateFailed("Invalid thunderstorm forecast time series")
    horizon = now + THUNDER_FORECAST_WINDOW
    points: dict[datetime, float | int | None] = {}
    for row in time_series:
        if not isinstance(row, dict):
            continue
        valid = _timestamp(row.get("time"))
        if valid is None or not now < valid <= horizon:
            continue
        row_data = row.get("data")
        probability = (
            _probability(row_data.get("thunderstorm_probability"))
            if isinstance(row_data, dict)
            else None
        )
        # Duplicate conflicting records cannot establish a reliable value.
        if valid in points and points[valid] != probability:
            points[valid] = None
        else:
            points[valid] = probability
    if not points:
        raise UpdateFailed("No future thunderstorm forecast for the selected location")
    forecast: list[ThunderForecastPoint] = [
        {"valid_time": valid.isoformat(), "probability": points[valid]}
        for valid in sorted(points)
    ]
    reference = _timestamp(payload.get("referenceTime"))
    latitude, longitude = _grid_point(payload)
    return {
        "created_time": created.isoformat(),
        "reference_time": reference.isoformat() if reference else None,
        "current": forecast[0],
        "forecast": forecast,
        "grid_latitude": latitude,
        "grid_longitude": longitude,
        "data_source_url": THUNDER_BASE_URL,
        "source_kind": "local_thunder_probability_forecast",
        "probability_unit": "%",
    }


class SmhiThunderClient:
    """Fetch only the required SNOW parameter after a new created time."""

    def __init__(
        self, session: ClientSession, latitude: float, longitude: float
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in (latitude, longitude)
        ) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid thunderstorm forecast coordinates")
        self._session = session
        self._url = (
            f"{THUNDER_BASE_URL}/geotype/point/lon/{longitude:.6f}"
            f"/lat/{latitude:.6f}/data.json?parameters=thunderstorm_probability"
        )
        self._payload: dict[str, Any] | None = None
        self._retry_at: datetime | None = None
        self._lock = asyncio.Lock()

    def parse_cached(self, now: datetime) -> ThunderData:
        """Re-evaluate age and the next forecast time without a network call."""
        return parse_thunder(self._payload, now)

    async def async_get_forecast(self, now: datetime) -> ThunderData:
        async with self._lock:
            if self._retry_at is not None and now < self._retry_at:
                raise UpdateFailed("Thunderstorm API rate limit is still active")
            if self._payload is not None:
                latest = await self._async_get_json(THUNDER_CREATED_TIME_URL, now)
                latest_created = _timestamp(latest.get("createdTime"))
                if latest_created is None:
                    raise UpdateFailed(
                        "Missing or invalid thunderstorm forecast creation time"
                    )
                if latest_created == _timestamp(self._payload.get("createdTime")):
                    return self.parse_cached(now)
            payload = await self._async_get_json(self._url, now)
            data = parse_thunder(payload, now)
            if self._payload is not None:
                previous_created = _timestamp(self._payload.get("createdTime"))
                if (
                    previous_created
                    and _timestamp(payload["createdTime"]) < previous_created
                ):
                    raise UpdateFailed("Thunderstorm API returned an older forecast")
            self._payload = payload
            return data

    async def _async_get_json(self, url: str, now: datetime) -> dict[str, Any]:
        try:
            async with self._session.get(
                url,
                timeout=ClientTimeout(total=20),
                headers={"Accept": "application/json"},
            ) as response:
                if response.status == 429:
                    self._retry_at = self._retry_time(
                        response.headers.get("Retry-After"), now
                    )
                    raise UpdateFailed("Thunderstorm API rate limit exceeded")
                if response.status != 200:
                    raise UpdateFailed(
                        f"Thunderstorm API returned HTTP {response.status}"
                    )
                payload = await response.json()
        except TimeoutError as err:
            raise UpdateFailed("Timed out fetching thunderstorm forecast") from err
        except ClientError as err:
            # Never include request URLs containing the selected coordinates.
            raise UpdateFailed("Unable to fetch thunderstorm forecast") from err
        except ValueError as err:
            raise UpdateFailed("Invalid thunderstorm forecast JSON response") from err
        if not isinstance(payload, dict):
            raise UpdateFailed("Invalid thunderstorm forecast response")
        return payload

    @staticmethod
    def _retry_time(value: str | None, now: datetime) -> datetime:
        try:
            seconds = float(value)
            if math.isfinite(seconds):
                return now + timedelta(seconds=max(1, min(seconds, 86400)))
        except (TypeError, ValueError):
            pass
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(now + timedelta(seconds=1), retry_at)
        except (TypeError, ValueError, OverflowError):
            return now + THUNDER_UPDATE_INTERVAL


class SmhiThunderCoordinator(DataUpdateCoordinator[ThunderData]):
    """Keep local model probabilities independent of issued weather warnings."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, latitude: float, longitude: float
    ) -> None:
        self._unsub_boundary: CALLBACK_TYPE | None = None
        super().__init__(
            hass,
            _LOGGER,
            name="local thunderstorm probability",
            config_entry=entry,
            update_interval=THUNDER_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = SmhiThunderClient(
            aiohttp_client.async_get_clientsession(hass), latitude, longitude
        )

    async def _async_update_data(self) -> ThunderData:
        await self._client.async_get_forecast(dt_util.utcnow())
        # Both valid-time selection and freshness use completion time. A slow
        # response must not undo a timer's time-slot change or revive stale data.
        now = dt_util.utcnow()
        data = self._client.parse_cached(now)
        self._schedule_boundary(data, now)
        return data

    @callback
    def _schedule_boundary(self, data: ThunderData, now: datetime) -> None:
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None
        if self._shutdown_requested:
            return
        deadlines = [
            timestamp
            for row in data["forecast"]
            if (timestamp := _timestamp(row["valid_time"])) is not None
            and timestamp > now
        ]
        created = _timestamp(data["created_time"])
        if created is not None and created + THUNDER_MAX_AGE > now:
            deadlines.append(created + THUNDER_MAX_AGE)
        if deadlines:
            self._unsub_boundary = async_track_point_in_utc_time(
                self.hass, self._async_boundary, min(deadlines)
            )

    @callback
    def _async_boundary(self, now: datetime) -> None:
        """Advance at an actual forecast time or expire the source exactly."""
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None
        if (
            self._shutdown_requested
            or not self.last_update_success
            or self.data is None
        ):
            return
        try:
            data = self._client.parse_cached(now)
        except UpdateFailed as err:
            self.async_set_update_error(err)
            return
        self.async_set_updated_data(data)
        self._schedule_boundary(data, now)

    async def async_shutdown(self) -> None:
        if self._unsub_boundary is not None:
            self._unsub_boundary()
            self._unsub_boundary = None
        await super().async_shutdown()
