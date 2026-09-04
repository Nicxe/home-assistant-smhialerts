"""SNOW probability, time selection, freshness and independent recovery tests."""

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

from custom_components.smhi_alerts.thunder import (
    THUNDER_CREATED_TIME_URL,
    SmhiThunderClient,
    SmhiThunderCoordinator,
    parse_thunder,
)

NOW = datetime(2026, 9, 4, 15, 30, tzinfo=UTC)


@pytest.fixture
def payload():
    """Public SMHI example lon16/lat58, retrieved 4 September 2026."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "thunder_point.json").read_text()
    )


def metadata(payload):
    return {key: payload[key] for key in ("createdTime", "referenceTime")}


def test_reads_actual_snow_format_without_percent_scaling(payload):
    data = parse_thunder(payload, NOW)
    assert data["current"] == {
        "valid_time": "2026-09-04T16:00:00+00:00",
        "probability": 9,
    }
    assert data["forecast"][0] == data["current"]
    assert data["grid_latitude"] == 57.996626
    assert data["grid_longitude"] == 16.011977
    assert data["source_kind"] == "local_thunder_probability_forecast"
    assert data["probability_unit"] == "%"
    assert "intervalParametersStartTime" not in data["current"]
    assert all(
        NOW < datetime.fromisoformat(row["valid_time"]) <= NOW + timedelta(hours=48)
        for row in data["forecast"]
    )


def test_exact_time_boundary_selects_next_future_timestamp(payload):
    data = parse_thunder(payload, datetime(2026, 9, 4, 16, tzinfo=UTC))
    assert data["current"]["valid_time"] == "2026-09-04T17:00:00+00:00"
    assert data["current"]["probability"] == 11


@pytest.mark.parametrize(
    "value", [9999, -1, -9, 101, True, "8", None, float("nan"), float("inf")]
)
def test_missing_nearest_probability_never_skips_to_later_known_value(payload, value):
    payload["timeSeries"][0]["data"]["thunderstorm_probability"] = value
    data = parse_thunder(payload, NOW)
    assert data["current"]["valid_time"].startswith("2026-09-04T16")
    assert data["current"]["probability"] is None
    assert data["forecast"][1]["probability"] == 11


@pytest.mark.parametrize("value", [0, 0.0, 0.5, 50, 100])
def test_valid_probabilities_preserved_including_zero(payload, value):
    payload["timeSeries"][0]["data"]["thunderstorm_probability"] = value
    assert parse_thunder(payload, NOW)["current"]["probability"] == value


@pytest.mark.parametrize("data", [None, [], {}, {"tstm": 75}])
def test_malformed_or_legacy_current_parameter_is_unknown(payload, data):
    payload["timeSeries"][0]["data"] = data
    assert parse_thunder(payload, NOW)["current"]["probability"] is None


def test_sort_deduplicate_and_reject_conflicting_duplicate_values(payload):
    original = deepcopy(payload["timeSeries"][0])
    payload["timeSeries"].reverse()
    payload["timeSeries"].append(original)
    data = parse_thunder(payload, NOW)
    assert data["current"]["probability"] == 9
    assert len({row["valid_time"] for row in data["forecast"]}) == len(data["forecast"])
    conflicting = deepcopy(original)
    conflicting["data"]["thunderstorm_probability"] = 75
    payload["timeSeries"].append(conflicting)
    assert parse_thunder(payload, NOW)["current"]["probability"] is None


def test_forecast_window_uses_time_not_number_of_rows(payload):
    payload["timeSeries"] = [
        {
            "time": (NOW + timedelta(hours=hours)).isoformat(),
            "data": {"thunderstorm_probability": hours},
        }
        for hours in (3, 6, 12, 24, 48, 49, 72)
    ]
    assert len(parse_thunder(payload, NOW)["forecast"]) == 5


@pytest.mark.parametrize(
    "created",
    [
        None,
        "invalid",
        "2026-09-04T15:00:00",
        "2026-09-04T13:30:00Z",
        "2026-09-04T15:46:00Z",
    ],
)
def test_invalid_expired_or_future_source_is_unavailable(payload, created):
    payload["createdTime"] = created
    with pytest.raises(UpdateFailed):
        parse_thunder(payload, NOW)


def test_recent_publication_cannot_make_past_rows_current(payload):
    payload["timeSeries"] = [
        {"time": "2026-09-04T15:00:00Z", "data": {"thunderstorm_probability": 99}}
    ]
    with pytest.raises(UpdateFailed, match="future"):
        parse_thunder(payload, NOW)


def test_all_probabilities_missing_keeps_fresh_dated_unknown_values(payload):
    for row in payload["timeSeries"]:
        row["data"]["thunderstorm_probability"] = 9999
    data = parse_thunder(payload, NOW)
    assert data["current"] == {
        "valid_time": "2026-09-04T16:00:00+00:00",
        "probability": None,
    }
    assert len(data["forecast"]) > 1
    assert all(row["probability"] is None for row in data["forecast"])


def test_invalid_timestamps_do_not_crash_or_replace_forecast(payload):
    payload["timeSeries"].extend(
        [
            {"time": "invalid", "data": {"thunderstorm_probability": 90}},
            {"time": "2026-09-04T16:00:00", "data": {"thunderstorm_probability": 90}},
            {
                "time": "0001-01-01T00:00:00+01:00",
                "data": {"thunderstorm_probability": 90},
            },
            None,
        ]
    )
    assert parse_thunder(payload, NOW)["current"]["probability"] == 9


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


async def test_unchanged_metadata_reuses_payload_and_reselects_time(payload):
    session = FakeSession(FakeResponse(payload), FakeResponse(metadata(payload)))
    client = SmhiThunderClient(session, 58, 16)
    assert (await client.async_get_forecast(NOW))["current"]["probability"] == 9
    assert (await client.async_get_forecast(NOW + timedelta(minutes=30)))["current"][
        "probability"
    ] == 11
    assert session.urls[1] == THUNDER_CREATED_TIME_URL
    assert session.urls[0].endswith("?parameters=thunderstorm_probability")


async def test_new_metadata_fetches_new_point_data(payload):
    newer = deepcopy(payload)
    newer["createdTime"] = "2026-09-04T15:29:00Z"
    newer["timeSeries"][0]["data"]["thunderstorm_probability"] = 0
    session = FakeSession(
        FakeResponse(payload), FakeResponse(metadata(newer)), FakeResponse(newer)
    )
    client = SmhiThunderClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    assert (await client.async_get_forecast(NOW))["current"]["probability"] == 0
    assert len(session.urls) == 3


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status=503),
        FakeResponse(error=ClientError("contains exact coordinates")),
        FakeResponse(error=TimeoutError()),
        FakeResponse([]),
    ],
)
async def test_failed_initial_request_recovers(payload, response):
    session = FakeSession(response, FakeResponse(payload))
    client = SmhiThunderClient(session, 58, 16)
    with pytest.raises(UpdateFailed) as error:
        await client.async_get_forecast(NOW)
    assert "coordinates" not in str(error.value)
    assert (await client.async_get_forecast(NOW))["current"]["probability"] == 9


async def test_failed_metadata_does_not_serve_cached_success(payload):
    session = FakeSession(
        FakeResponse(payload), FakeResponse(status=503), FakeResponse(metadata(payload))
    )
    client = SmhiThunderClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed):
        await client.async_get_forecast(NOW)
    assert (await client.async_get_forecast(NOW))["current"]


async def test_rate_limit_honors_retry_after(payload):
    session = FakeSession(
        FakeResponse(status=429, headers={"Retry-After": "1800"}), FakeResponse(payload)
    )
    client = SmhiThunderClient(session, 58, 16)
    with pytest.raises(UpdateFailed, match="rate limit"):
        await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed, match="rate limit"):
        await client.async_get_forecast(NOW + timedelta(minutes=15))
    assert len(session.urls) == 1
    assert (await client.async_get_forecast(NOW + timedelta(minutes=30)))["current"]


async def test_coordinator_recovers_and_timer_does_not_resurrect_outage(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = FakeSession(
        FakeResponse(status=503), FakeResponse(payload), FakeResponse(status=503)
    )
    with (
        patch(
            "custom_components.smhi_alerts.thunder.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch("custom_components.smhi_alerts.thunder.dt_util.utcnow", return_value=NOW),
    ):
        coordinator = SmhiThunderCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        await coordinator.async_refresh()
        coordinator._async_boundary(NOW + timedelta(minutes=30))
        assert not coordinator.last_update_success
        assert len(session.urls) == 3
        await coordinator.async_shutdown()


async def test_timer_advances_forecast_then_expires_source_without_network(
    hass, payload
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = FakeSession(FakeResponse(payload))
    with (
        patch(
            "custom_components.smhi_alerts.thunder.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch("custom_components.smhi_alerts.thunder.dt_util.utcnow", return_value=NOW),
        patch(
            "custom_components.smhi_alerts.thunder.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiThunderCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        assert track.call_args.args[2] == datetime(2026, 9, 4, 16, tzinfo=UTC)
        coordinator._async_boundary(datetime(2026, 9, 4, 16, tzinfo=UTC))
        assert coordinator.data["current"]["probability"] == 11
        coordinator._async_boundary(datetime(2026, 9, 4, 17, tzinfo=UTC))
        assert track.call_args.args[2] == datetime(2026, 9, 4, 17, 14, 57, tzinfo=UTC)
        coordinator._async_boundary(datetime(2026, 9, 4, 17, 14, 57, tzinfo=UTC))
        assert not coordinator.last_update_success
        assert len(session.urls) == 1
        await coordinator.async_shutdown()
        assert coordinator._unsub_boundary is None


@pytest.mark.parametrize("initial", [False, True])
async def test_response_crossing_forecast_boundary_uses_completion_time(
    hass, payload, initial
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    clock = {"now": NOW}
    delayed = DelayedResponse(payload if initial else metadata(payload))
    session = FakeSession(*([delayed] if initial else [FakeResponse(payload), delayed]))
    with (
        patch(
            "custom_components.smhi_alerts.thunder.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.thunder.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
    ):
        coordinator = SmhiThunderCoordinator(hass, entry, 58, 16)
        if not initial:
            await coordinator.async_refresh()
        clock["now"] = datetime(2026, 9, 4, 15, 59, 59, tzinfo=UTC)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        clock["now"] = datetime(2026, 9, 4, 16, 0, 1, tzinfo=UTC)
        if not initial:
            coordinator._async_boundary(clock["now"])
        delayed.release.set()
        await pending
        assert coordinator.data["current"]["valid_time"].startswith("2026-09-04T17")
        await coordinator.async_shutdown()


async def test_source_expiring_during_io_is_unavailable(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    delayed = DelayedResponse(payload)
    session = FakeSession(delayed)
    clock = {"now": datetime(2026, 9, 4, 17, 14, 56, tzinfo=UTC)}
    with (
        patch(
            "custom_components.smhi_alerts.thunder.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.thunder.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
    ):
        coordinator = SmhiThunderCoordinator(hass, entry, 58, 16)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        clock["now"] += timedelta(seconds=2)
        delayed.release.set()
        await pending
        assert not coordinator.last_update_success
        await coordinator.async_shutdown()


async def test_shutdown_during_request_cannot_create_a_new_timer(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    delayed = DelayedResponse(payload)
    session = FakeSession(delayed)
    with (
        patch(
            "custom_components.smhi_alerts.thunder.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch("custom_components.smhi_alerts.thunder.dt_util.utcnow", return_value=NOW),
        patch(
            "custom_components.smhi_alerts.thunder.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiThunderCoordinator(hass, entry, 58, 16)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        await coordinator.async_shutdown()
        delayed.release.set()
        await pending
        track.assert_not_called()
        assert coordinator._unsub_boundary is None


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 0), (0, 181), (float("nan"), 16), (58, float("inf")), (True, 16), ("58", 16)],
)
def test_invalid_coordinates_rejected_before_network(latitude, longitude):
    session = FakeSession()
    with pytest.raises(ValueError):
        SmhiThunderClient(session, latitude, longitude)
    assert not session.urls


async def test_invalid_new_forecast_is_not_cached(payload):
    invalid = deepcopy(payload)
    invalid["createdTime"] = "2026-09-04T15:29:00Z"
    invalid["timeSeries"] = []
    valid = deepcopy(payload)
    valid["createdTime"] = invalid["createdTime"]
    session = FakeSession(
        FakeResponse(payload),
        FakeResponse(metadata(invalid)),
        FakeResponse(invalid),
        FakeResponse(metadata(valid)),
        FakeResponse(valid),
    )
    client = SmhiThunderClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed):
        await client.async_get_forecast(NOW)
    assert (await client.async_get_forecast(NOW))["created_time"].startswith(
        "2026-09-04T15:29"
    )
    assert len(session.urls) == 5


async def test_older_forecast_cannot_replace_newer_cache(payload):
    older = deepcopy(payload)
    older["createdTime"] = "2026-09-04T15:00:00Z"
    session = FakeSession(
        FakeResponse(payload), FakeResponse(metadata(older)), FakeResponse(older)
    )
    client = SmhiThunderClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed, match="older forecast"):
        await client.async_get_forecast(NOW)
    assert client.parse_cached(NOW)["created_time"].startswith("2026-09-04T15:14")


def test_retry_after_http_date_and_malformed_fallback():
    assert SmhiThunderClient._retry_time(
        "Fri, 04 Sep 2026 16:00:00 GMT", NOW
    ) == NOW + timedelta(minutes=30)
    assert SmhiThunderClient._retry_time("invalid", NOW) == NOW + timedelta(minutes=15)


def test_large_clock_shift_filters_elapsed_and_missing_rows_without_interpolation(
    payload,
):
    payload["createdTime"] = "2026-10-25T00:00:00Z"
    payload["timeSeries"] = [
        {"time": "2026-10-25T02:00:00+02:00", "data": {"thunderstorm_probability": 7}},
        {"time": "2026-10-25T02:00:00+01:00", "data": {"thunderstorm_probability": 13}},
        {"time": "2026-10-25T04:00:00+01:00", "data": {"thunderstorm_probability": 20}},
    ]
    result = parse_thunder(payload, datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
    assert result["current"] == {
        "valid_time": "2026-10-25T01:00:00+00:00",
        "probability": 13,
    }
    assert len(result["forecast"]) == 2
