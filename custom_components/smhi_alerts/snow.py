"""Shared SMHI SNOW point transport, caching and source validation."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import math
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from homeassistant.helpers.update_coordinator import UpdateFailed

SNOW_BASE_URL = (
    "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
)
SNOW_CREATED_TIME_URL = f"{SNOW_BASE_URL}/createdtime.json"
SNOW_UPDATE_INTERVAL = timedelta(minutes=15)
SNOW_MAX_AGE = timedelta(hours=2)
SNOW_FUTURE_TOLERANCE = timedelta(minutes=15)
SNOW_FORECAST_WINDOW = timedelta(hours=48)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


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


def validate_snow(payload: Any, now: datetime) -> None:
    """Reject invalid sources before replacing a previously usable cache."""
    if not isinstance(payload, dict):
        raise UpdateFailed("Invalid SNOW forecast response")
    created = _timestamp(payload.get("createdTime"))
    if created is None:
        raise UpdateFailed("Missing or invalid SNOW forecast creation time")
    if now - created >= SNOW_MAX_AGE:
        raise UpdateFailed("SNOW forecast is stale")
    if created - now > SNOW_FUTURE_TOLERANCE:
        raise UpdateFailed("SNOW forecast creation time is in the future")
    rows = payload.get("timeSeries")
    if not isinstance(rows, list):
        raise UpdateFailed("Invalid SNOW forecast time series")
    if not any(
        isinstance(row, dict)
        and (valid := _timestamp(row.get("time"))) is not None
        and now < valid <= now + SNOW_FORECAST_WINDOW
        for row in rows
    ):
        raise UpdateFailed("No future SNOW forecast for the selected location")


class SmhiSnowClient:
    """Cache a selected SNOW point and share it across forecast consumers."""

    def __init__(
        self,
        session: ClientSession,
        latitude: float,
        longitude: float,
        *,
        parameters: tuple[str, ...],
        cache_interval: timedelta = timedelta(0),
    ) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float))
            for value in (latitude, longitude)
        ) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Invalid SNOW forecast coordinates")
        self._session = session
        self._url = (
            f"{SNOW_BASE_URL}/geotype/point/lon/{longitude:.6f}"
            f"/lat/{latitude:.6f}/data.json?parameters={','.join(parameters)}"
        )
        self._cache_interval = cache_interval
        self._checked_at: datetime | None = None
        self._payload: dict[str, Any] | None = None
        self._retry_at: datetime | None = None
        self._lock = asyncio.Lock()

    def cached_payload(self, now: datetime) -> dict[str, Any]:
        """Validate freshness again when consumers advance locally."""
        validate_snow(self._payload, now)
        return self._payload

    async def async_get_payload(self, now: datetime) -> dict[str, Any]:
        async with self._lock:
            if self._retry_at is not None and now < self._retry_at:
                raise UpdateFailed("SNOW API rate limit is still active")
            if (
                self._payload is not None
                and self._checked_at is not None
                and timedelta(0) <= now - self._checked_at < self._cache_interval
            ):
                return self.cached_payload(now)
            if self._payload is not None:
                latest = await self._async_get_json(SNOW_CREATED_TIME_URL, now)
                latest_created = _timestamp(latest.get("createdTime"))
                if latest_created is None:
                    raise UpdateFailed("Missing or invalid SNOW forecast creation time")
                if latest_created == _timestamp(self._payload.get("createdTime")):
                    result = self.cached_payload(now)
                    self._checked_at = now
                    return result
            payload = await self._async_get_json(self._url, now)
            validate_snow(payload, now)
            if self._payload is not None:
                previous_created = _timestamp(self._payload.get("createdTime"))
                if (
                    previous_created
                    and _timestamp(payload["createdTime"]) < previous_created
                ):
                    raise UpdateFailed("SNOW API returned an older forecast")
            self._payload = payload
            self._checked_at = now
            return payload

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
                    raise UpdateFailed("SNOW API rate limit exceeded")
                if response.status != 200:
                    raise UpdateFailed(f"SNOW API returned HTTP {response.status}")
                payload = await response.json()
        except TimeoutError as err:
            raise UpdateFailed("Timed out fetching SNOW forecast") from err
        except ClientError as err:
            # Never include request URLs containing the selected coordinates.
            raise UpdateFailed("Unable to fetch SNOW forecast") from err
        except ValueError as err:
            raise UpdateFailed("Invalid SNOW forecast JSON response") from err
        if not isinstance(payload, dict):
            raise UpdateFailed("Invalid SNOW forecast response")
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
            return now + SNOW_UPDATE_INTERVAL
