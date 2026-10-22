"""SNOW precipitation amounts and probabilities for their full source intervals."""

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
PRECIPITATION_PARAMETERS = ("probability_of_precipitation", "precipitation_amount_mean")


class PrecipitationForecastPoint(TypedDict):
    """Water-equivalent total and probability over one unmodified source interval."""

    valid_time: str
    interval_start: str | None
    probability: float | int | None
    amount: float | int | None


class PrecipitationData(TypedDict):
    created_time: str
    reference_time: str | None
    current: PrecipitationForecastPoint
    forecast: list[PrecipitationForecastPoint]
    grid_latitude: float | None
    grid_longitude: float | None
    data_source_url: str
    source_kind: str
    probability_unit: str
    amount_unit: str


def _number(value: Any, *, maximum: float | None = None) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        if (
            math.isfinite(value)
            and 0 <= value != 9999
            and (maximum is None or value <= maximum)
        ):
            return value
    except OverflowError:
        pass
    return None


def parse_precipitation(payload: Any, now: datetime) -> PrecipitationData:
    """Keep missing or malformed periods unknown, without skipping timestamps.

    SMHI gives the total in kg/m² (equivalent to mm of water) for the complete
    interval ending at ``time``. Intervals may already have started and may
    last 1, 3, 6 or 12h. No values are divided, prorated, accumulated or added.
    """
    validate_snow(payload, now)
    horizon = now + SNOW_FORECAST_WINDOW
    points: dict[datetime, PrecipitationForecastPoint] = {}
    for row in payload["timeSeries"]:
        if not isinstance(row, dict):
            continue
        valid = _timestamp(row.get("time"))
        if valid is None or not now < valid <= horizon:
            continue
        start = _timestamp(row.get("intervalParametersStartTime"))
        interval_valid = start is not None and timedelta(
            0
        ) < valid - start <= timedelta(hours=12)
        values = row.get("data")
        if not isinstance(values, dict):
            values = {}
        point: PrecipitationForecastPoint = {
            "valid_time": valid.isoformat(),
            "interval_start": start.isoformat() if interval_valid else None,
            "probability": _number(
                values.get("probability_of_precipitation"), maximum=100
            )
            if interval_valid
            else None,
            "amount": _number(values.get("precipitation_amount_mean"))
            if interval_valid
            else None,
        }
        if valid in points:
            previous = points[valid]
            if point["interval_start"] != previous["interval_start"]:
                point.update(interval_start=None, probability=None, amount=None)
            else:
                for key in ("probability", "amount"):
                    if point[key] != previous[key]:
                        point[key] = None
        points[valid] = point
    forecast = [points[valid] for valid in sorted(points)]
    created = _timestamp(payload["createdTime"])
    reference = _timestamp(payload.get("referenceTime"))
    latitude, longitude = _grid_point(payload)
    return {
        "created_time": created.isoformat(),
        "reference_time": reference.isoformat() if reference else None,
        "current": forecast[0],
        "forecast": forecast,
        "grid_latitude": latitude,
        "grid_longitude": longitude,
        "data_source_url": SNOW_BASE_URL,
        "source_kind": "local_precipitation_forecast",
        "probability_unit": "%",
        "amount_unit": "mm",
    }


class SmhiPrecipitationCoordinator(DataUpdateCoordinator[PrecipitationData]):
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
            name="local precipitation forecast",
            config_entry=entry,
            update_interval=SNOW_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = client or SmhiSnowClient(
            aiohttp_client.async_get_clientsession(hass),
            latitude,
            longitude,
            parameters=PRECIPITATION_PARAMETERS,
        )

    async def _async_update_data(self) -> PrecipitationData:
        await self._client.async_get_payload(dt_util.utcnow())
        # A response crossing a time boundary cannot revive stale source data.
        now = dt_util.utcnow()
        data = parse_precipitation(self._client.cached_payload(now), now)
        self._schedule_boundary(data, now)
        return data

    @callback
    def _schedule_boundary(self, data: PrecipitationData, now: datetime) -> None:
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
            data = parse_precipitation(self._client.cached_payload(now), now)
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
