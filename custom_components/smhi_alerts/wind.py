"""Local SNOW wind gust forecasts with a conservatively complete 24h maximum."""

from datetime import datetime, timedelta
import logging
import math
from typing import Any, TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .snow import (
    SNOW_BASE_URL,
    SNOW_FORECAST_WINDOW,
    SNOW_MAX_AGE,
    SNOW_UPDATE_INTERVAL,
    SmhiSnowClient,
    _grid_point,
    _timestamp,
    validate_snow,
)

_LOGGER = logging.getLogger(__name__)
WIND_PARAMETERS = ("wind_speed_of_gust",)


class WindForecastPoint(TypedDict):
    """Wind gust speed at an actual SMHI forecast timestamp."""

    valid_time: str
    gust: float | int | None


class WindData(TypedDict):
    created_time: str
    reference_time: str | None
    current: WindForecastPoint
    forecast: list[WindForecastPoint]
    max_gust_24h: float | int | None
    max_gust_time: str | None
    max_window_end: str
    max_complete: bool
    grid_latitude: float | None
    grid_longitude: float | None
    data_source_url: str
    source_kind: str
    wind_unit: str


def _gust(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        if math.isfinite(value) and 0 <= value != 9999:
            return value
    except OverflowError:
        pass
    return None


def parse_wind(payload: Any, now: datetime) -> WindData:
    """Never label a partial source window as a complete 24h maximum.

    The near-term SNOW timeline is hourly. A maximum is only offered when
    every actual source point in the next 24h is usable, no gap exceeds an
    hour, and the source reaches the window end. Values outside the window
    establish coverage only; they never enter the maximum calculation.
    """
    validate_snow(payload, now)
    horizon = now + SNOW_FORECAST_WINDOW
    window_end = now + timedelta(hours=24)
    points: dict[datetime, float | int | None] = {}
    invalid_timestamp = False
    for row in payload["timeSeries"]:
        valid = _timestamp(row.get("time")) if isinstance(row, dict) else None
        if valid is None:
            invalid_timestamp = True
            continue
        if not now < valid <= horizon:
            continue
        values = row.get("data")
        gust = (
            _gust(values.get("wind_speed_of_gust"))
            if isinstance(values, dict)
            else None
        )
        if valid in points and points[valid] != gust:
            gust = None
        points[valid] = gust
    times = sorted(points)
    forecast: list[WindForecastPoint] = [
        {"valid_time": valid.isoformat(), "gust": points[valid]} for valid in times
    ]
    within = [valid for valid in times if valid <= window_end]
    following = next((valid for valid in times if valid >= window_end), None)
    coverage = [now, *within]
    if following is not None and following not in within:
        coverage.append(following)
    complete = bool(
        within
        and following is not None
        and not invalid_timestamp
        and all(points[valid] is not None for valid in within)
        and all(
            right - left <= timedelta(hours=1)
            for left, right in zip(coverage, coverage[1:], strict=False)
        )
    )
    maximum_time = max(within, key=lambda valid: points[valid]) if complete else None
    created = _timestamp(payload["createdTime"])
    reference = _timestamp(payload.get("referenceTime"))
    latitude, longitude = _grid_point(payload)
    return {
        "created_time": created.isoformat(),
        "reference_time": reference.isoformat() if reference else None,
        "current": forecast[0],
        "forecast": forecast,
        "max_gust_24h": points[maximum_time] if maximum_time else None,
        "max_gust_time": maximum_time.isoformat() if maximum_time else None,
        "max_window_end": window_end.isoformat(),
        "max_complete": complete,
        "grid_latitude": latitude,
        "grid_longitude": longitude,
        "data_source_url": SNOW_BASE_URL,
        "source_kind": "local_wind_forecast",
        "wind_unit": "m/s",
    }


class SmhiWindCoordinator(DataUpdateCoordinator[WindData]):
    """Advance exact forecast times locally without affecting issued warnings."""

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
            name="local wind forecast",
            config_entry=entry,
            update_interval=SNOW_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = client or SmhiSnowClient(
            aiohttp_client.async_get_clientsession(hass),
            latitude,
            longitude,
            parameters=WIND_PARAMETERS,
        )

    async def _async_update_data(self) -> WindData:
        await self._client.async_get_payload(dt_util.utcnow())
        # A response crossing a time boundary cannot revive stale source data.
        now = dt_util.utcnow()
        data = parse_wind(self._client.cached_payload(now), now)
        self._schedule_boundary(data, now)
        return data

    @callback
    def _schedule_boundary(self, data: WindData, now: datetime) -> None:
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
        if created is not None and created + SNOW_MAX_AGE > now:
            deadlines.append(created + SNOW_MAX_AGE)
        if deadlines:
            self._unsub_boundary = async_track_point_in_utc_time(
                self.hass, self._async_boundary, min(deadlines)
            )

    @callback
    def _async_boundary(self, now: datetime) -> None:
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
            data = parse_wind(self._client.cached_payload(now), now)
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
