"""MESAN past-period semantics, source freshness, cache and independent timers."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientError
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.mesan import (
    MESAN_CREATED_TIME_URL,
    MESAN_MAX_AGE,
    MESAN_PARAMETERS,
    MESAN_UPDATE_INTERVAL,
    SmhiMesanClient,
    SmhiMesanCoordinator,
    parse_mesan,
)

NOW = datetime(2026, 10, 22, 15, 45, tzinfo=UTC)
CREATED = datetime(2026, 10, 22, 15, 40, 37, tzinfo=UTC)


class FakeResponse:
    def __init__(self, payload=None, status=200, headers=None, error=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return deepcopy(self.payload)


class DelayedResponse(FakeResponse):
    def __init__(self, payload):
        super().__init__(payload)
        self.requested = asyncio.Event()
        self.release = asyncio.Event()

    async def json(self):
        self.requested.set()
        await self.release.wait()
        return await super().json()


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.fixture
def payload():
    """Public SMHI point lon12/lat58, retrieved 22 October 2026."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "mesan_point.json").read_text()
    )


def metadata(payload):
    return {key: payload[key] for key in ("createdTime", "referenceTime")}


def test_latest_past_hour_and_history_preserve_analysis_semantics(payload):
    result = parse_mesan(payload, NOW)
    assert result["current"] == {
        "valid_time": "2026-10-22T15:00:00+00:00",
        "precipitation": 0.01,
        "snow_change": 0.0,
    }
    assert result["current"] == result["history"][0]
    assert result["source_kind"] == "local_weather_analysis"
    assert result["precipitation_unit"] == "mm"
    assert result["snow_change_unit"] == "cm"
    assert result["grid_latitude"] == 58.008376
    assert result["grid_longitude"] == 11.99605
    assert len(result["history"]) == 24
    times = [datetime.fromisoformat(row["valid_time"]) for row in result["history"]]
    assert times == sorted(times, reverse=True)
    assert all(NOW - timedelta(hours=24) < valid <= NOW for valid in times)
    assert "forecast" not in result
    assert "total" not in result["current"]


def test_time_window_excludes_future_old_and_invalid_records_even_when_unsorted(
    payload,
):
    payload["timeSeries"].reverse()
    payload["timeSeries"].extend(
        [
            {
                "time": "2026-10-22T16:00:00Z",
                "data": dict.fromkeys(MESAN_PARAMETERS, 99),
            },
            {
                "time": (NOW - timedelta(hours=24)).isoformat(),
                "data": dict.fromkeys(MESAN_PARAMETERS, 99),
            },
            {
                "time": "2026-10-22T15:30:00",
                "data": dict.fromkeys(MESAN_PARAMETERS, 99),
            },
            {"time": "invalid", "data": dict.fromkeys(MESAN_PARAMETERS, 99)},
            None,
        ]
    )
    assert parse_mesan(payload, NOW)["current"]["precipitation"] == 0.01
    assert len(parse_mesan(payload, NOW)["history"]) == 24
    exact = parse_mesan(payload, datetime(2026, 10, 22, 16, tzinfo=UTC))
    assert exact["current"]["valid_time"] == "2026-10-22T16:00:00+00:00"
    assert exact["current"]["precipitation"] == 99


@pytest.mark.parametrize("change", [-15.2, -0.1, 0, 0.25, 100])
def test_signed_snow_change_is_not_clamped_or_added_to_snow_depth(payload, change):
    payload["timeSeries"][0]["data"][MESAN_PARAMETERS[1]] = change
    result = parse_mesan(payload, NOW)
    assert result["current"]["snow_change"] == change
    assert result["current"]["precipitation"] == 0.01


@pytest.mark.parametrize(
    "value", [9999, -1, -9, True, "0.5", None, float("nan"), float("inf"), 10**400]
)
def test_invalid_precipitation_stays_unknown_without_skipping_latest_time(
    payload, value
):
    payload["timeSeries"][0]["data"][MESAN_PARAMETERS[0]] = value
    result = parse_mesan(payload, NOW)
    assert result["current"]["valid_time"] == "2026-10-22T15:00:00+00:00"
    assert result["current"]["precipitation"] is None
    assert result["current"]["snow_change"] == 0
    assert result["history"][1]["precipitation"] == 0.05


@pytest.mark.parametrize(
    "value", [9999, True, "-0.5", None, float("nan"), float("inf"), 10**400]
)
def test_invalid_snow_change_stays_unknown_independently(payload, value):
    payload["timeSeries"][0]["data"][MESAN_PARAMETERS[1]] = value
    current = parse_mesan(payload, NOW)["current"]
    assert current["snow_change"] is None
    assert current["precipitation"] == 0.01


@pytest.mark.parametrize("values", [None, [], {}, {"legacy": 50}])
def test_latest_unknown_values_are_retained_and_zero_is_real(payload, values):
    payload["timeSeries"][0]["data"] = values
    result = parse_mesan(payload, NOW)
    assert result["current"]["precipitation"] is None
    assert result["current"]["snow_change"] is None
    assert result["current"]["valid_time"] == "2026-10-22T15:00:00+00:00"
    payload["timeSeries"][0]["data"] = dict.fromkeys(MESAN_PARAMETERS, 0)
    current = parse_mesan(payload, NOW)["current"]
    assert current["precipitation"] == current["snow_change"] == 0


def test_conflicting_duplicate_fields_remain_unknown_after_third_record(payload):
    original = deepcopy(payload["timeSeries"][0])
    duplicate = deepcopy(original)
    duplicate["data"][MESAN_PARAMETERS[1]] = -0.4
    payload["timeSeries"].extend([duplicate, original])
    result = parse_mesan(payload, NOW)
    assert result["current"]["snow_change"] is None
    assert result["current"]["precipitation"] == 0.01
    assert len(result["history"]) == 24


@pytest.mark.parametrize(
    "created",
    [
        None,
        "invalid",
        "2026-10-22T15:40:00",
        "2026-10-22T12:45:00Z",
        "2026-10-22T15:50:01Z",
    ],
)
def test_missing_expired_or_future_source_fails(payload, created):
    payload["createdTime"] = created
    with pytest.raises(UpdateFailed):
        parse_mesan(payload, NOW)


@pytest.mark.parametrize(
    "rows", [None, {}, [], [{"time": "2026-10-22T16:00:00Z", "data": {}}]]
)
def test_no_recent_past_period_is_unavailable(payload, rows):
    payload["timeSeries"] = rows
    with pytest.raises(UpdateFailed):
        parse_mesan(payload, NOW)


async def test_unchanged_created_time_reuses_point_data(payload):
    session = FakeSession(FakeResponse(payload), FakeResponse(metadata(payload)))
    client = SmhiMesanClient(session, 58, 12)
    first = await client.async_get_analysis(NOW)
    second = await client.async_get_analysis(NOW + timedelta(minutes=30))
    assert first["current"] == second["current"]
    assert session.urls[1] == MESAN_CREATED_TIME_URL
    assert all(parameter in session.urls[0] for parameter in MESAN_PARAMETERS)
    assert len(session.urls) == 2


async def test_new_created_time_downloads_updated_point(payload):
    newer = deepcopy(payload)
    newer["createdTime"] = "2026-10-22T16:10:00Z"
    newer["timeSeries"].insert(
        0, {"time": "2026-10-22T16:00:00Z", "data": dict.fromkeys(MESAN_PARAMETERS, 0)}
    )
    session = FakeSession(
        FakeResponse(payload), FakeResponse(metadata(newer)), FakeResponse(newer)
    )
    client = SmhiMesanClient(session, 58, 12)
    await client.async_get_analysis(NOW)
    result = await client.async_get_analysis(NOW + timedelta(minutes=30))
    assert result["current"] == {
        "valid_time": "2026-10-22T16:00:00+00:00",
        "precipitation": 0,
        "snow_change": 0,
    }
    assert len(session.urls) == 3


async def test_older_point_does_not_replace_valid_cache(payload):
    older = deepcopy(payload)
    older["createdTime"] = "2026-10-22T15:10:00Z"
    session = FakeSession(
        FakeResponse(payload), FakeResponse(metadata(older)), FakeResponse(older)
    )
    client = SmhiMesanClient(session, 58, 12)
    await client.async_get_analysis(NOW)
    with pytest.raises(UpdateFailed, match="older analysis"):
        await client.async_get_analysis(NOW)
    assert client.parse_cached(NOW)["created_time"] == CREATED.isoformat()


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status=503),
        FakeResponse(error=ClientError("contains coordinates")),
        FakeResponse(error=TimeoutError()),
        FakeResponse([]),
    ],
)
async def test_initial_transport_failure_recovers_without_coordinate_leaks(
    payload, response
):
    session = FakeSession(response, FakeResponse(payload))
    client = SmhiMesanClient(session, 58, 12)
    with pytest.raises(UpdateFailed) as error:
        await client.async_get_analysis(NOW)
    assert "coordinates" not in str(error.value)
    assert (await client.async_get_analysis(NOW))["current"]["precipitation"] == 0.01


async def test_metadata_failure_does_not_serve_old_cache_as_success(payload):
    session = FakeSession(
        FakeResponse(payload), FakeResponse(status=503), FakeResponse(metadata(payload))
    )
    client = SmhiMesanClient(session, 58, 12)
    await client.async_get_analysis(NOW)
    with pytest.raises(UpdateFailed):
        await client.async_get_analysis(NOW)
    assert (await client.async_get_analysis(NOW))["current"]["precipitation"] == 0.01


async def test_rate_limit_honors_retry_after(payload):
    session = FakeSession(
        FakeResponse(status=429, headers={"Retry-After": "1800"}), FakeResponse(payload)
    )
    client = SmhiMesanClient(session, 58, 12)
    for now in [NOW, NOW + timedelta(minutes=29)]:
        with pytest.raises(UpdateFailed, match="rate limit"):
            await client.async_get_analysis(now)
    assert len(session.urls) == 1
    assert (await client.async_get_analysis(NOW + timedelta(minutes=30)))["current"]


@pytest.mark.parametrize(
    "point", [(True, 12), (58, float("nan")), (91, 12), (58, -181)]
)
def test_invalid_coordinates_rejected_before_io(point):
    session = FakeSession()
    with pytest.raises(ValueError):
        SmhiMesanClient(session, *point)
    assert not session.urls


async def test_source_expires_exactly_without_polling_and_shutdown_cancels_timer(
    hass, payload
):
    session = FakeSession(FakeResponse(payload))
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.smhi_alerts.mesan.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch("custom_components.smhi_alerts.mesan.dt_util.utcnow", return_value=NOW),
        patch(
            "custom_components.smhi_alerts.mesan.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiMesanCoordinator(hass, entry, 58, 12)
        assert coordinator.update_interval == MESAN_UPDATE_INTERVAL
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert track.call_args.args[2] == CREATED + MESAN_MAX_AGE
        coordinator._async_expire(CREATED + MESAN_MAX_AGE)
        assert not coordinator.last_update_success
        assert len(session.urls) == 1
        await coordinator.async_shutdown()
        assert coordinator._unsub_expiry is None
        assert coordinator._shutdown_requested


async def test_api_outage_cannot_be_revived_by_expiry_callback_and_retry_recovers(
    hass, payload
):
    session = FakeSession(
        FakeResponse(payload), FakeResponse(status=503), FakeResponse(metadata(payload))
    )
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.smhi_alerts.mesan.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch("custom_components.smhi_alerts.mesan.dt_util.utcnow", return_value=NOW),
    ):
        coordinator = SmhiMesanCoordinator(hass, entry, 58, 12)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        coordinator._async_expire(NOW + timedelta(minutes=10))
        assert not coordinator.last_update_success
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        await coordinator.async_shutdown()


async def test_slow_response_crossing_expiry_cannot_publish_old_analysis(hass, payload):
    delayed = DelayedResponse(payload)
    session = FakeSession(delayed)
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    clock = {"now": CREATED + MESAN_MAX_AGE - timedelta(seconds=1)}
    with (
        patch(
            "custom_components.smhi_alerts.mesan.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.mesan.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
    ):
        coordinator = SmhiMesanCoordinator(hass, entry, 58, 12)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        clock["now"] += timedelta(seconds=2)
        delayed.release.set()
        await pending
        assert not coordinator.last_update_success
        await coordinator.async_shutdown()
