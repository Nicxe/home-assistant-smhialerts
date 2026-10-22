"""Local thunderstorm probabilities from SMHI SNOW point forecasts."""

from datetime import datetime, timedelta
import logging
from typing import Any, TypedDict

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .snow import (
    SNOW_BASE_URL,
    SNOW_CREATED_TIME_URL,
    SmhiSnowClient,
    _grid_point,
    _timestamp,
)

_LOGGER = logging.getLogger(__name__)

THUNDER_BASE_URL = SNOW_BASE_URL
THUNDER_CREATED_TIME_URL = SNOW_CREATED_TIME_URL
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


def _probability(value: Any) -> float | int | None:
    """SNOW provides percent already; 9999 and malformed values are unknown."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 100
    ):
        return None
    return value


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


class SmhiThunderClient(SmhiSnowClient):
    """Keep the thunder-only client API while reusing shared SNOW transport."""

    def __init__(
        self, session: ClientSession, latitude: float, longitude: float
    ) -> None:
        super().__init__(
            session, latitude, longitude, parameters=("thunderstorm_probability",)
        )

    def parse_cached(self, now: datetime) -> ThunderData:
        return parse_thunder(self.cached_payload(now), now)

    async def async_get_forecast(self, now: datetime) -> ThunderData:
        return parse_thunder(await self.async_get_payload(now), now)


class SmhiThunderCoordinator(DataUpdateCoordinator[ThunderData]):
    """Keep local model probabilities independent of issued weather warnings."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        latitude: float,
        longitude: float,
        *,
        client: SmhiSnowClient | None = None,
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
        self._client = client or SmhiThunderClient(
            aiohttp_client.async_get_clientsession(hass), latitude, longitude
        )

    async def _async_update_data(self) -> ThunderData:
        await self._client.async_get_payload(dt_util.utcnow())
        # Both valid-time selection and freshness use completion time. A slow
        # response must not undo a timer's time-slot change or revive stale data.
        now = dt_util.utcnow()
        data = parse_thunder(self._client.cached_payload(now), now)
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
            data = parse_thunder(self._client.cached_payload(now), now)
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
