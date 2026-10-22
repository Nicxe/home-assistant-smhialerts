"""Optional local MESAN analyses of past precipitation and snow amount change."""

import asyncio
from datetime import datetime, timedelta
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

from .snow import _grid_point, _timestamp

_LOGGER = logging.getLogger(__name__)

MESAN_BASE_URL = (
    "https://opendata-download-metanalys.smhi.se/api/category/mesan2g/version/3"
)
MESAN_CREATED_TIME_URL = f"{MESAN_BASE_URL}/createdtime.json"
MESAN_UPDATE_INTERVAL = timedelta(minutes=30)
# Integration policy: expire source data after three hours without a new analysis.
MESAN_MAX_AGE = timedelta(hours=3)
MESAN_FUTURE_TOLERANCE = timedelta(minutes=5)
MESAN_HISTORY_WINDOW = timedelta(hours=24)
MESAN_PARAMETERS = (
    "precipitation_amount_last_1_hours",
    "change_over_time_in_surface_snow_amount_1_hours",
)


class MesanAnalysisPoint(TypedDict):
    """Analysed amounts for the one-hour period ending at valid_time."""

    valid_time: str
    precipitation: float | int | None
    snow_change: float | int | None


class MesanData(TypedDict):
    """Latest past analysis and bounded individual periods, never a rolling sum."""

    created_time: str
    reference_time: str | None
    current: MesanAnalysisPoint
    history: list[MesanAnalysisPoint]
    grid_latitude: float | None
    grid_longitude: float | None
    data_source_url: str
    precipitation_unit: str
    snow_change_unit: str
    source_kind: str


def _number(value: Any, *, signed: bool = False) -> float | int | None:
    """Keep zero and signed snow changes, but reject unknown or invalid data."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value == 9999 or (not signed and value < 0):
            return None
    except OverflowError:
        return None
    return value


def parse_mesan(payload: Any, now: datetime) -> MesanData:
    """Select the latest analysed past period without inferring observations.

    Both parameters describe the last hour ending at ``time``. Snow amount
    change is signed, distinct from total snow depth and fresh snowfall. Every
    valid period remains in history even if one or both values are unknown.
    """
    if not isinstance(payload, dict):
        raise UpdateFailed("Invalid weather analysis response")
    created = _timestamp(payload.get("createdTime"))
    if created is None:
        raise UpdateFailed("Missing or invalid weather analysis creation time")
    if now - created >= MESAN_MAX_AGE:
        raise UpdateFailed("Weather analysis is stale")
    if created - now > MESAN_FUTURE_TOLERANCE:
        raise UpdateFailed("Weather analysis creation time is in the future")
    rows = payload.get("timeSeries")
    if not isinstance(rows, list):
        raise UpdateFailed("Invalid weather analysis time series")
    earliest = now - MESAN_HISTORY_WINDOW
    points: dict[datetime, MesanAnalysisPoint] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        valid = _timestamp(row.get("time"))
        if valid is None or not earliest < valid <= now:
            continue
        values = row.get("data")
        if not isinstance(values, dict):
            values = {}
        point: MesanAnalysisPoint = {
            "valid_time": valid.isoformat(),
            "precipitation": _number(values.get(MESAN_PARAMETERS[0])),
            "snow_change": _number(values.get(MESAN_PARAMETERS[1]), signed=True),
        }
        if valid in points:
            previous = points[valid]
            for key in ("precipitation", "snow_change"):
                if point[key] != previous[key]:
                    point[key] = None
        points[valid] = point
    if not points:
        raise UpdateFailed("No recent past weather analysis for the selected location")
    history = [points[valid] for valid in sorted(points, reverse=True)]
    reference = _timestamp(payload.get("referenceTime"))
    latitude, longitude = _grid_point(payload)
    return {
        "created_time": created.isoformat(),
        "reference_time": reference.isoformat() if reference else None,
        "current": history[0],
        "history": history,
        "grid_latitude": latitude,
        "grid_longitude": longitude,
        "data_source_url": MESAN_BASE_URL,
        "source_kind": "local_weather_analysis",
        "precipitation_unit": "mm",
        "snow_change_unit": "cm",
    }


class SmhiMesanClient:
    """Fetch one selected point, reusing its data when creation time is unchanged."""

    def __init__(
        self, session: ClientSession, latitude: float, longitude: float
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in (latitude, longitude)
        ) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid weather analysis coordinates")
        self._session = session
        self._url = (
            f"{MESAN_BASE_URL}/geotype/point/lon/{longitude:.6f}"
            f"/lat/{latitude:.6f}/data.json?parameters={','.join(MESAN_PARAMETERS)}"
        )
        self._payload: dict[str, Any] | None = None
        self._retry_at: datetime | None = None
        self._lock = asyncio.Lock()

    def parse_cached(self, now: datetime) -> MesanData:
        """Re-evaluate freshness and the past-period window without downloading."""
        return parse_mesan(self._payload, now)

    async def async_get_analysis(self, now: datetime) -> MesanData:
        async with self._lock:
            if self._retry_at is not None and now < self._retry_at:
                raise UpdateFailed("Weather analysis API rate limit is still active")
            if self._payload is not None:
                latest = await self._async_get_json(MESAN_CREATED_TIME_URL, now)
                latest_created = _timestamp(latest.get("createdTime"))
                if latest_created is None:
                    raise UpdateFailed(
                        "Missing or invalid weather analysis creation time"
                    )
                if latest_created == _timestamp(self._payload.get("createdTime")):
                    return self.parse_cached(now)
            payload = await self._async_get_json(self._url, now)
            data = parse_mesan(payload, now)
            if self._payload is not None:
                previous_created = _timestamp(self._payload.get("createdTime"))
                if (
                    previous_created
                    and _timestamp(payload["createdTime"]) < previous_created
                ):
                    raise UpdateFailed(
                        "Weather analysis API returned an older analysis"
                    )
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
                    # Respect Retry-After using the established SNOW transport policy.
                    from .snow import SmhiSnowClient

                    self._retry_at = SmhiSnowClient._retry_time(
                        response.headers.get("Retry-After"), now
                    )
                    raise UpdateFailed("Weather analysis API rate limit exceeded")
                if response.status != 200:
                    raise UpdateFailed(
                        f"Weather analysis API returned HTTP {response.status}"
                    )
                payload = await response.json()
        except TimeoutError as err:
            raise UpdateFailed("Timed out fetching weather analysis") from err
        except ClientError as err:
            # Do not expose a request URL containing the chosen coordinates.
            raise UpdateFailed("Unable to fetch weather analysis") from err
        except ValueError as err:
            raise UpdateFailed("Invalid weather analysis JSON response") from err
        if not isinstance(payload, dict):
            raise UpdateFailed("Invalid weather analysis response")
        return payload


class SmhiMesanCoordinator(DataUpdateCoordinator[MesanData]):
    """Keep past weather analysis independent of forecasts and official warnings."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, latitude: float, longitude: float
    ) -> None:
        self._unsub_expiry: CALLBACK_TYPE | None = None
        super().__init__(
            hass,
            _LOGGER,
            name="local weather analysis",
            config_entry=entry,
            update_interval=MESAN_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = SmhiMesanClient(
            aiohttp_client.async_get_clientsession(hass), latitude, longitude
        )

    async def _async_update_data(self) -> MesanData:
        await self._client.async_get_analysis(dt_util.utcnow())
        # Recheck completion time so a slow response cannot revive expired data.
        data = self._client.parse_cached(dt_util.utcnow())
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None
        if not self._shutdown_requested:
            self._unsub_expiry = async_track_point_in_utc_time(
                self.hass,
                self._async_expire,
                _timestamp(data["created_time"]) + MESAN_MAX_AGE,
            )
        return data

    @callback
    def _async_expire(self, now: datetime) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None
        if self._shutdown_requested or not self.last_update_success:
            return
        self.async_set_update_error(UpdateFailed("Weather analysis is stale"))

    async def async_shutdown(self) -> None:
        if self._unsub_expiry is not None:
            self._unsub_expiry()
            self._unsub_expiry = None
        await super().async_shutdown()
