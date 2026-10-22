"""Local winter weather forecasts from SMHI SNOW, separate from warnings."""

from datetime import datetime
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

WINTER_PARAMETERS = (
    "predominant_precipitation_type_at_surface",
    "probability_of_frozen_precipitation",
    "air_temperature",
)
PRECIPITATION_TYPES = (
    "none",
    "rain",
    "thunderstorm",
    "freezing_rain",
    "mixed_ice",
    "snow",
    "wet_snow",
    "rain_snow",
    "ice_pellets",
    "graupel",
    "hail",
    "drizzle",
    "freezing_drizzle",
)


class WinterForecastPoint(TypedDict):
    """Separate source values at one exact forecast time, with no inferred risk."""

    valid_time: str
    precipitation_type: str | None
    precipitation_type_code: int | None
    frozen_probability: float | None
    temperature: float | int | None


class WinterData(TypedDict):
    """Bounded upcoming point forecasts and source metadata."""

    created_time: str
    reference_time: str | None
    current: WinterForecastPoint
    forecast: list[WinterForecastPoint]
    grid_latitude: float | None
    grid_longitude: float | None
    data_source_url: str
    source_kind: str
    probability_unit: str
    temperature_unit: str


def _finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value != 9999
    )


def _precipitation_code(value: Any) -> int | None:
    if (
        not _finite_number(value)
        or value != int(value)
        or not 0 <= value < len(PRECIPITATION_TYPES)
    ):
        return None
    return int(value)


def _frozen_probability(value: Any) -> float | None:
    """SNOW's frozen probability is a fraction, unlike thunder's percentage."""
    if not _finite_number(value) or not 0 <= value <= 1:
        return None
    return round(float(value) * 100, 10)


def parse_winter(payload: Any, now: datetime) -> WinterData:
    """Preserve every actual time and unknown field without interpolation.

    These parameters are valid at the given time. They do not establish snow
    depth, an accumulated snowfall amount, surface ice or an official warning.
    """
    validate_snow(payload, now)
    horizon = now + SNOW_FORECAST_WINDOW
    points: dict[datetime, WinterForecastPoint] = {}
    for row in payload["timeSeries"]:
        if not isinstance(row, dict):
            continue
        valid = _timestamp(row.get("time"))
        if valid is None or not now < valid <= horizon:
            continue
        values = row.get("data")
        if not isinstance(values, dict):
            values = {}
        code = _precipitation_code(
            values.get("predominant_precipitation_type_at_surface")
        )
        temperature = values.get("air_temperature")
        point: WinterForecastPoint = {
            "valid_time": valid.isoformat(),
            "precipitation_type": PRECIPITATION_TYPES[code]
            if code is not None
            else None,
            "precipitation_type_code": code,
            "frozen_probability": _frozen_probability(
                values.get("probability_of_frozen_precipitation")
            ),
            "temperature": temperature if _finite_number(temperature) else None,
        }
        if valid in points:
            # Conflicting duplicates only make the affected values unknown.
            previous = points[valid]
            for key in (
                "precipitation_type",
                "precipitation_type_code",
                "frozen_probability",
                "temperature",
            ):
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
        "source_kind": "local_winter_forecast",
        "probability_unit": "%",
        "temperature_unit": "°C",
    }


class SmhiWinterCoordinator(DataUpdateCoordinator[WinterData]):
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
            name="local winter weather",
            config_entry=entry,
            update_interval=SNOW_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = client or SmhiSnowClient(
            aiohttp_client.async_get_clientsession(hass),
            latitude,
            longitude,
            parameters=WINTER_PARAMETERS,
        )

    async def _async_update_data(self) -> WinterData:
        await self._client.async_get_payload(dt_util.utcnow())
        # A response crossing a time boundary cannot revive stale source data.
        now = dt_util.utcnow()
        data = parse_winter(self._client.cached_payload(now), now)
        self._schedule_boundary(data, now)
        return data

    @callback
    def _schedule_boundary(self, data: WinterData, now: datetime) -> None:
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
            data = parse_winter(self._client.cached_payload(now), now)
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
