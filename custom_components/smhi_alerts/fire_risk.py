"""Daily local fire risk forecasts, separate from issued SMHI warnings."""

import asyncio
from datetime import UTC, datetime, time, timedelta
from email.utils import parsedate_to_datetime
import logging
import math
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

FIRE_RISK_BASE_URL = (
    "https://opendata-download-metfcst.smhi.se/api/category/fwif1g/version/1/daily"
)
FIRE_RISK_APPROVED_TIME_URL = f"{FIRE_RISK_BASE_URL}/approvedtime.json"
FIRE_RISK_UPDATE_INTERVAL = timedelta(minutes=30)
# SMHI approves daily forecasts four times a day. Three missed cycles makes
# the source stale, even if its time series still includes future dates.
FIRE_RISK_MAX_AGE = timedelta(hours=18)
FIRE_RISK_FUTURE_TOLERANCE = timedelta(minutes=15)
FIRE_RISK_FORECAST_DAYS = 6
SWEDEN_TIME_ZONE = ZoneInfo("Europe/Stockholm")

FOREST_FIRE_RISK_STATES = {
    1: "very_low",
    2: "low",
    3: "moderate",
    4: "high",
    5: "very_high",
    6: "extreme",  # SMHI's public label is 5E.
}
GRASS_FIRE_RISK_STATES = {
    1: "snow_covered",
    2: "season_over",
    3: "low",
    4: "moderate",
    5: "high",
    6: "very_high",
}
FOREST_DRYNESS_STATES = {
    1: "very_wet",
    2: "wet",
    3: "moderately_wet",
    4: "dry",
    5: "very_dry",
    6: "extremely_dry",  # Also labelled 5E by SMHI.
}
_PARAMETER_STATES = {
    "fwiindex": ("forest_fire_risk", FOREST_FIRE_RISK_STATES),
    "grassfire": ("grass_fire_risk", GRASS_FIRE_RISK_STATES),
    "forestdry": ("forest_dryness", FOREST_DRYNESS_STATES),
}


class FireRiskDay(TypedDict):
    """One Swedish calendar day's forecast classes."""

    date: str
    valid_time: str
    forest_fire_risk: str | None
    grass_fire_risk: str | None
    forest_dryness: str | None
    forest_fire_risk_code: int | None
    grass_fire_risk_code: int | None
    forest_dryness_code: int | None


class FireRiskData(TypedDict):
    """Fresh source metadata and a bounded forecast."""

    approved_time: str
    reference_time: str | None
    current: FireRiskDay | None
    forecast: list[FireRiskDay]
    grid_latitude: float | None
    grid_longitude: float | None
    data_source_url: str


def _timestamp(value: Any) -> datetime | None:
    """Accept only explicit timezone-aware ISO timestamps."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def _class_code(values: Any, states: dict[int, str]) -> int | None:
    """Missing values and unsupported classes are unknown, never zero risk."""
    if not isinstance(values, list) or len(values) != 1:
        return None
    value = values[0]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value not in states
    ):
        return None
    return int(value)


def _grid_point(payload: dict[str, Any]) -> tuple[float | None, float | None]:
    """Accept SMHI's nested single-point geometry and standard GeoJSON Point."""
    geometry = payload.get("geometry")
    if not isinstance(geometry, dict):
        return None, None
    coordinates = geometry.get("coordinates")
    if isinstance(coordinates, list) and len(coordinates) == 1:
        coordinates = coordinates[0]
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return None, None
    longitude, latitude = coordinates
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
        for value in coordinates
    ):
        return None, None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None, None
    return float(latitude), float(longitude)


def parse_fire_risk(payload: Any, now: datetime) -> FireRiskData:
    """Validate a daily point response and select today using Swedish local time.

    Daily FWI describes the afternoon, and daily grassfire describes the day's
    highest class. They are daily forecasts, not current observed conditions.
    Reference time can be several days older than approval by design.
    """
    if not isinstance(payload, dict):
        raise UpdateFailed("Invalid fire risk response")
    approved = _timestamp(payload.get("approvedTime"))
    if approved is None:
        raise UpdateFailed("Missing or invalid fire risk approval time")
    if now - approved > FIRE_RISK_MAX_AGE:
        raise UpdateFailed("Fire risk forecast is stale")
    if approved - now > FIRE_RISK_FUTURE_TOLERANCE:
        raise UpdateFailed("Fire risk approval time is in the future")
    time_series = payload.get("timeSeries")
    if not isinstance(time_series, list):
        raise UpdateFailed("Invalid fire risk time series")

    today = now.astimezone(SWEDEN_TIME_ZONE).date()
    end_date = today + timedelta(days=FIRE_RISK_FORECAST_DAYS)
    days: dict[str, FireRiskDay] = {}
    for row in time_series:
        if not isinstance(row, dict):
            continue
        valid_time = _timestamp(row.get("validTime"))
        if valid_time is None:
            continue
        try:
            local_day = valid_time.astimezone(SWEDEN_TIME_ZONE).date()
        except OverflowError:
            continue
        if not today <= local_day < end_date:
            continue
        parameters = row.get("parameters")
        if not isinstance(parameters, list):
            continue
        day: FireRiskDay = {
            "date": local_day.isoformat(),
            "valid_time": valid_time.isoformat(),
            "forest_fire_risk": None,
            "grass_fire_risk": None,
            "forest_dryness": None,
            "forest_fire_risk_code": None,
            "grass_fire_risk_code": None,
            "forest_dryness_code": None,
        }
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            name = parameter.get("name")
            if not isinstance(name, str) or name not in _PARAMETER_STATES:
                continue
            key, states = _PARAMETER_STATES[name]
            code = _class_code(parameter.get("values"), states)
            day[key] = states.get(code)
            day[f"{key}_code"] = code
        previous = days.get(day["date"])
        # A daily response normally has one row per day. If duplicated, pick
        # the latest valid time deterministically rather than input ordering.
        if previous is None or day["valid_time"] > previous["valid_time"]:
            days[day["date"]] = day

    if not days:
        raise UpdateFailed("No current or upcoming fire risk forecast")
    forecast = [days[key] for key in sorted(days)]
    if not any(
        day[key] is not None
        for day in forecast
        for key in ("forest_fire_risk", "grass_fire_risk", "forest_dryness")
    ):
        raise UpdateFailed("No usable fire risk forecast for the selected location")
    reference = _timestamp(payload.get("referenceTime"))
    latitude, longitude = _grid_point(payload)
    return {
        "approved_time": approved.isoformat(),
        "reference_time": reference.isoformat() if reference else None,
        "current": days.get(today.isoformat()),
        "forecast": forecast,
        "grid_latitude": latitude,
        "grid_longitude": longitude,
        "data_source_url": FIRE_RISK_BASE_URL,
    }


class SmhiFireRiskClient:
    """Fetch a selected point only when SMHI approves a new daily forecast."""

    def __init__(
        self, session: ClientSession, latitude: float, longitude: float
    ) -> None:
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            for value in (latitude, longitude)
        ) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid fire risk coordinates")
        self._session = session
        self._url = (
            f"{FIRE_RISK_BASE_URL}/geotype/point/"
            f"lon/{longitude:.6f}/lat/{latitude:.6f}/data.json"
        )
        self._payload: dict[str, Any] | None = None
        self._retry_at: datetime | None = None
        self._lock = asyncio.Lock()

    def parse_cached(self, now: datetime) -> FireRiskData:
        """Re-evaluate source age and calendar day without a network request."""
        return parse_fire_risk(self._payload, now)

    async def async_get_forecast(self, now: datetime) -> FireRiskData:
        """Return fresh data or raise; a failed fetch never looks like low risk."""
        async with self._lock:
            if self._retry_at is not None and now < self._retry_at:
                raise UpdateFailed("Fire risk API rate limit is still active")
            if self._payload is not None:
                latest = await self._async_get_json(FIRE_RISK_APPROVED_TIME_URL, now)
                latest_approved = _timestamp(latest.get("approvedTime"))
                if latest_approved is None:
                    raise UpdateFailed("Missing or invalid fire risk approval time")
                if latest_approved == _timestamp(self._payload.get("approvedTime")):
                    return self.parse_cached(now)
            payload = await self._async_get_json(self._url, now)
            result = parse_fire_risk(payload, now)
            if self._payload is not None:
                previous_approved = _timestamp(self._payload.get("approvedTime"))
                if (
                    previous_approved
                    and _timestamp(payload["approvedTime"]) < previous_approved
                ):
                    raise UpdateFailed("Fire risk API returned an older forecast")
            # Cache only a fully validated response. Failed first requests can
            # recover on a later poll without reloading the integration.
            self._payload = payload
            return result

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
                    raise UpdateFailed("Fire risk API rate limit exceeded")
                if response.status != 200:
                    raise UpdateFailed(f"Fire risk API returned HTTP {response.status}")
                payload = await response.json()
        except TimeoutError as err:
            raise UpdateFailed("Timed out fetching fire risk data") from err
        except ClientError as err:
            # Client errors can include the URL with the user's coordinates.
            raise UpdateFailed("Unable to fetch fire risk data") from err
        except ValueError as err:
            raise UpdateFailed("Invalid fire risk JSON response") from err
        if not isinstance(payload, dict):
            raise UpdateFailed("Invalid fire risk response")
        return payload

    @staticmethod
    def _retry_time(value: str | None, now: datetime) -> datetime:
        """Respect seconds or HTTP-date without sleeping inside an update."""
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
            return now + FIRE_RISK_UPDATE_INTERVAL


class SmhiFireRiskCoordinator(DataUpdateCoordinator[FireRiskData]):
    """Coordinate local forecasts independently of official warning updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        latitude: float,
        longitude: float,
    ) -> None:
        self._unsub_midnight: CALLBACK_TYPE | None = None
        super().__init__(
            hass,
            _LOGGER,
            name="local fire risk",
            config_entry=entry,
            update_interval=FIRE_RISK_UPDATE_INTERVAL,
            always_update=False,
        )
        self._client = SmhiFireRiskClient(
            aiohttp_client.async_get_clientsession(hass), latitude, longitude
        )
        self._schedule_midnight(dt_util.utcnow())

    async def _async_update_data(self) -> FireRiskData:
        await self._client.async_get_forecast(dt_util.utcnow())
        # A network response may cross midnight or the source-age limit. Use
        # completion time so it cannot overwrite the calendar timer with an
        # older day's result or make expired data available again.
        return self._client.parse_cached(dt_util.utcnow())

    @callback
    def _schedule_midnight(self, now: datetime) -> None:
        if self._unsub_midnight is not None:
            self._unsub_midnight()
        tomorrow = now.astimezone(SWEDEN_TIME_ZONE).date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, time(), SWEDEN_TIME_ZONE)
        self._unsub_midnight = async_track_point_in_utc_time(
            self.hass, self._async_midnight, midnight.astimezone(UTC)
        )

    @callback
    def _async_midnight(self, now: datetime) -> None:
        """Change the displayed day exactly at Swedish midnight from cache."""
        if self._shutdown_requested:
            return
        self._schedule_midnight(now)
        # A failed source must recover through a successful network request,
        # not become available just because the calendar changed.
        if not self.last_update_success or self.data is None:
            return
        try:
            data = self._client.parse_cached(now)
        except UpdateFailed as err:
            self.async_set_update_error(err)
            return
        self.async_set_updated_data(data)

    async def async_shutdown(self) -> None:
        """Cancel the calendar timer as well as coordinator polling."""
        if self._unsub_midnight is not None:
            self._unsub_midnight()
            self._unsub_midnight = None
        await super().async_shutdown()
