"""Verify SMHI's daily classes, calendar selection and isolated API recovery."""

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

from custom_components.smhi_alerts.fire_risk import (
    FIRE_RISK_APPROVED_TIME_URL,
    SmhiFireRiskClient,
    SmhiFireRiskCoordinator,
    parse_fire_risk,
)

NOW = datetime(2026, 9, 4, 13, tzinfo=UTC)


@pytest.fixture
def payload():
    """Public SMHI example point lon16/lat58, retrieved 4 September 2026."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "fire_risk_daily.json").read_text()
    )


def _set_class(row, name, value):
    for parameter in row["parameters"]:
        if parameter["name"] == name:
            parameter["values"] = [value]
            return
    raise AssertionError(f"Parameter {name} missing from fixture")


def test_current_day_uses_timestamp_not_first_row(payload):
    result = parse_fire_risk(payload, NOW)
    assert result["current"]["date"] == "2026-09-04"
    assert result["current"]["forest_fire_risk"] == "low"
    assert result["current"]["forest_fire_risk_code"] == 2
    assert result["current"]["grass_fire_risk"] is None
    assert result["current"]["forest_dryness"] == "dry"
    assert [day["date"] for day in result["forecast"]] == [
        f"2026-09-{day:02d}" for day in range(4, 10)
    ]
    assert result["reference_time"].startswith("2026-09-02")
    assert result["grid_longitude"] == 16.011823
    assert result["grid_latitude"] == 57.99705


@pytest.mark.parametrize(
    ("code", "forest", "grass", "dryness"),
    [
        (1, "very_low", "snow_covered", "very_wet"),
        (2, "low", "season_over", "wet"),
        (3, "moderate", "low", "moderately_wet"),
        (4, "high", "moderate", "dry"),
        (5, "very_high", "high", "very_dry"),
        (6, "extreme", "very_high", "extremely_dry"),
    ],
)
def test_distinct_smhi_class_scales(payload, code, forest, grass, dryness):
    row = payload["timeSeries"][1]
    for name in ("fwiindex", "grassfire", "forestdry"):
        _set_class(row, name, float(code))
    current = parse_fire_risk(payload, NOW)["current"]
    assert current["forest_fire_risk"] == forest
    assert current["grass_fire_risk"] == grass
    assert current["forest_dryness"] == dryness
    assert current["forest_fire_risk_code"] == code


@pytest.mark.parametrize(
    "value", [-1, 0, 7, 9999, -9, 1.5, True, "5", None, float("nan"), float("inf")]
)
def test_invalid_parameter_never_becomes_low_risk(payload, value):
    _set_class(payload["timeSeries"][1], "fwiindex", value)
    current = parse_fire_risk(payload, NOW)["current"]
    assert current["forest_fire_risk"] is None
    assert current["forest_fire_risk_code"] is None
    assert current["forest_dryness"] == "dry"


def test_missing_parameter_preserves_other_parameters(payload):
    row = payload["timeSeries"][1]
    row["parameters"] = [p for p in row["parameters"] if p["name"] != "fwiindex"]
    _set_class(row, "grassfire", 1)
    current = parse_fire_risk(payload, NOW)["current"]
    assert current["forest_fire_risk"] is None
    assert current["grass_fire_risk"] == "snow_covered"
    assert current["forest_dryness"] == "dry"


def test_unsorted_rows_and_invalid_timestamps(payload):
    payload["timeSeries"].reverse()
    payload["timeSeries"].insert(0, {"validTime": "invalid", "parameters": []})
    result = parse_fire_risk(payload, NOW)
    assert result["current"]["date"] == "2026-09-04"
    assert result["forecast"][0] == result["current"]


@pytest.mark.parametrize(
    ("before", "after", "approved", "valid_times"),
    [
        (
            "2026-03-28T22:59:59Z",
            "2026-03-28T23:00:00Z",
            "2026-03-28T20:00:00Z",
            ["2026-03-28T12:00:00Z", "2026-03-29T12:00:00Z"],
        ),
        (
            "2026-03-29T21:59:59Z",
            "2026-03-29T22:00:00Z",
            "2026-03-29T20:00:00Z",
            ["2026-03-29T12:00:00Z", "2026-03-30T12:00:00Z"],
        ),
        (
            "2026-10-25T22:59:59Z",
            "2026-10-25T23:00:00Z",
            "2026-10-25T20:00:00Z",
            ["2026-10-25T12:00:00Z", "2026-10-26T12:00:00Z"],
        ),
    ],
)
def test_swedish_calendar_boundaries_and_dst(
    payload, before, after, approved, valid_times
):
    payload["approvedTime"] = approved
    rows = payload["timeSeries"][1:3]
    for row, valid in zip(rows, valid_times, strict=True):
        row["validTime"] = valid
    payload["timeSeries"] = rows
    assert parse_fire_risk(payload, datetime.fromisoformat(before))["current"][
        "valid_time"
    ].startswith(valid_times[0][:10])
    assert parse_fire_risk(payload, datetime.fromisoformat(after))["current"][
        "valid_time"
    ].startswith(valid_times[1][:10])


@pytest.mark.parametrize(
    "value",
    [
        None,
        "bad",
        "2026-09-04T10:00:00",
        "2026-09-03T18:00:00Z",
        "2026-09-04T13:16:00Z",
    ],
)
def test_invalid_stale_or_future_approval_is_unavailable(payload, value):
    payload["approvedTime"] = value
    with pytest.raises(UpdateFailed):
        parse_fire_risk(payload, NOW)


def test_new_approval_does_not_make_old_forecast_current(payload):
    payload["timeSeries"] = payload["timeSeries"][:1]
    with pytest.raises(UpdateFailed, match="No current or upcoming"):
        parse_fire_risk(payload, NOW)


def test_future_only_does_not_claim_today(payload):
    payload["timeSeries"] = payload["timeSeries"][2:]
    result = parse_fire_risk(payload, NOW)
    assert result["current"] is None
    assert result["forecast"][0]["date"] == "2026-09-05"


def test_missing_all_classes_is_unavailable(payload):
    for row in payload["timeSeries"]:
        for name in ("fwiindex", "grassfire", "forestdry"):
            _set_class(row, name, -1)
    with pytest.raises(UpdateFailed, match="No usable"):
        parse_fire_risk(payload, NOW)


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


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def approval(payload):
    return {key: payload[key] for key in ("approvedTime", "referenceTime")}


async def test_unchanged_approval_reuses_payload_and_recomputes_day(payload):
    session = FakeSession(FakeResponse(payload), FakeResponse(approval(payload)))
    client = SmhiFireRiskClient(session, 58, 16)
    result = await client.async_get_forecast(NOW)
    assert result["current"]["date"] == "2026-09-04"
    result = await client.async_get_forecast(datetime(2026, 9, 4, 22, tzinfo=UTC))
    assert result["current"]["date"] == "2026-09-05"
    assert len(session.urls) == 2
    assert session.urls[1] == FIRE_RISK_APPROVED_TIME_URL


async def test_changed_approval_fetches_new_point_data(payload):
    newer = deepcopy(payload)
    newer["approvedTime"] = "2026-09-04T12:00:00Z"
    _set_class(newer["timeSeries"][1], "fwiindex", 6)
    session = FakeSession(
        FakeResponse(payload), FakeResponse(approval(newer)), FakeResponse(newer)
    )
    client = SmhiFireRiskClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    result = await client.async_get_forecast(NOW)
    assert result["current"]["forest_fire_risk"] == "extreme"
    assert len(session.urls) == 3


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status=503),
        FakeResponse(error=ClientError("with secret coordinates")),
        FakeResponse(error=TimeoutError()),
        FakeResponse(payload=[]),
    ],
)
async def test_failed_first_fetch_recovers_without_recreating_client(payload, response):
    session = FakeSession(response, FakeResponse(payload))
    client = SmhiFireRiskClient(session, 58, 16)
    with pytest.raises(UpdateFailed) as error:
        await client.async_get_forecast(NOW)
    assert "secret coordinates" not in str(error.value)
    assert (await client.async_get_forecast(NOW))["current"][
        "forest_fire_risk"
    ] == "low"


async def test_failed_metadata_does_not_silently_serve_old_data(payload):
    session = FakeSession(
        FakeResponse(payload), FakeResponse(status=500), FakeResponse(approval(payload))
    )
    client = SmhiFireRiskClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed):
        await client.async_get_forecast(NOW)
    assert (await client.async_get_forecast(NOW))["current"] is not None


async def test_rate_limit_honors_retry_after(payload):
    session = FakeSession(
        FakeResponse(status=429, headers={"Retry-After": "3600"}), FakeResponse(payload)
    )
    client = SmhiFireRiskClient(session, 58, 16)
    with pytest.raises(UpdateFailed, match="rate limit"):
        await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed, match="rate limit"):
        await client.async_get_forecast(NOW + timedelta(minutes=30))
    assert len(session.urls) == 1
    assert (await client.async_get_forecast(NOW + timedelta(hours=1)))["current"]


async def test_coordinator_can_start_unavailable_and_recover(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = FakeSession(FakeResponse(status=503), FakeResponse(payload))
    with (
        patch(
            "custom_components.smhi_alerts.fire_risk.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.fire_risk.dt_util.utcnow", return_value=NOW
        ),
    ):
        coordinator = SmhiFireRiskCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert coordinator.data["current"]["forest_fire_risk"] == "low"
        await coordinator.async_shutdown()


async def test_midnight_recalculates_without_network_and_shutdown_cleans_timer(
    hass, payload
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = FakeSession(FakeResponse(payload))
    with (
        patch(
            "custom_components.smhi_alerts.fire_risk.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.fire_risk.dt_util.utcnow", return_value=NOW
        ),
    ):
        coordinator = SmhiFireRiskCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        assert coordinator.data["current"]["date"] == "2026-09-04"
        coordinator._async_midnight(datetime(2026, 9, 4, 22, tzinfo=UTC))
        assert coordinator.data["current"]["date"] == "2026-09-05"
        assert len(session.urls) == 1
        assert coordinator._unsub_midnight is not None
        await coordinator.async_shutdown()
        assert coordinator._unsub_midnight is None


async def test_stale_cache_cannot_be_refreshed_by_unchanged_metadata(payload):
    session = FakeSession(FakeResponse(payload), FakeResponse(approval(payload)))
    client = SmhiFireRiskClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed, match="stale"):
        await client.async_get_forecast(NOW + timedelta(hours=18))
    assert len(session.urls) == 2


async def test_invalid_new_payload_is_not_cached(payload):
    invalid = deepcopy(payload)
    invalid["approvedTime"] = "2026-09-04T12:00:00Z"
    invalid["timeSeries"] = []
    valid = deepcopy(payload)
    valid["approvedTime"] = invalid["approvedTime"]
    session = FakeSession(
        FakeResponse(payload),
        FakeResponse(approval(invalid)),
        FakeResponse(invalid),
        FakeResponse(approval(valid)),
        FakeResponse(valid),
    )
    client = SmhiFireRiskClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed):
        await client.async_get_forecast(NOW)
    assert (await client.async_get_forecast(NOW))["approved_time"].startswith(
        "2026-09-04T12"
    )
    assert len(session.urls) == 5


async def test_api_regression_does_not_replace_newer_forecast(payload):
    older = deepcopy(payload)
    older["approvedTime"] = "2026-09-04T08:00:00Z"
    session = FakeSession(
        FakeResponse(payload), FakeResponse(approval(older)), FakeResponse(older)
    )
    client = SmhiFireRiskClient(session, 58, 16)
    await client.async_get_forecast(NOW)
    with pytest.raises(UpdateFailed, match="older forecast"):
        await client.async_get_forecast(NOW)
    assert client.parse_cached(NOW)["approved_time"].startswith("2026-09-04T10")


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (91, 0),
        (-91, 0),
        (0, 181),
        (0, -181),
        (float("nan"), 16),
        (58, float("inf")),
        (True, 16),
        ("58", 16),
    ],
)
def test_invalid_coordinates_fail_before_network(latitude, longitude):
    session = FakeSession()
    with pytest.raises(ValueError, match="coordinates"):
        SmhiFireRiskClient(session, latitude, longitude)
    assert not session.urls


def test_http_date_retry_after():
    assert SmhiFireRiskClient._retry_time(
        "Fri, 04 Sep 2026 14:00:00 GMT", NOW
    ) == NOW + timedelta(hours=1)
    assert SmhiFireRiskClient._retry_time("invalid", NOW) == NOW + timedelta(minutes=30)


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ("2026-03-29T00:00:00Z", "2026-03-29T22:00:00Z"),
        ("2026-10-25T00:00:00Z", "2026-10-25T23:00:00Z"),
    ],
)
async def test_calendar_timer_schedules_real_swedish_midnight(hass, start, expected):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.smhi_alerts.fire_risk.dt_util.utcnow",
            return_value=datetime.fromisoformat(start),
        ),
        patch(
            "custom_components.smhi_alerts.fire_risk.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiFireRiskCoordinator(hass, entry, 58, 16)
        assert track.call_args.args[2] == datetime.fromisoformat(expected)
        await coordinator.async_shutdown()
        track.return_value.assert_called_once()


async def test_midnight_does_not_restore_failed_source_from_cache(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = FakeSession(FakeResponse(payload), FakeResponse(status=503))
    with (
        patch(
            "custom_components.smhi_alerts.fire_risk.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.fire_risk.dt_util.utcnow", return_value=NOW
        ),
    ):
        coordinator = SmhiFireRiskCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        coordinator._async_midnight(datetime(2026, 9, 4, 22, tzinfo=UTC))
        assert not coordinator.last_update_success
        assert len(session.urls) == 2
        await coordinator.async_shutdown()


class DelayedResponse(FakeResponse):
    """Pause a real client response while the test advances the clock."""

    def __init__(self, payload):
        super().__init__(payload)
        self.requested = asyncio.Event()
        self.release = asyncio.Event()

    async def json(self):
        self.requested.set()
        await self.release.wait()
        return await super().json()


async def test_late_response_cannot_overwrite_midnight_day_change(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    clock = {"now": NOW}
    delayed = DelayedResponse(approval(payload))
    session = FakeSession(FakeResponse(payload), delayed)
    with (
        patch(
            "custom_components.smhi_alerts.fire_risk.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.fire_risk.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
    ):
        coordinator = SmhiFireRiskCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        clock["now"] = datetime(2026, 9, 4, 21, 59, 59, tzinfo=UTC)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        clock["now"] = datetime(2026, 9, 4, 22, 0, 1, tzinfo=UTC)
        coordinator._async_midnight(clock["now"])
        assert coordinator.data["current"]["date"] == "2026-09-05"
        delayed.release.set()
        await pending
        assert coordinator.data["current"]["date"] == "2026-09-05"
        assert len(session.urls) == 2
        await coordinator.async_shutdown()


async def test_forecast_expiring_during_io_is_rejected_at_completion(hass, payload):
    payload["approvedTime"] = "2026-09-04T04:00:00Z"
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    clock = {"now": NOW}
    delayed = DelayedResponse(approval(payload))
    session = FakeSession(FakeResponse(payload), delayed)
    with (
        patch(
            "custom_components.smhi_alerts.fire_risk.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.fire_risk.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
    ):
        coordinator = SmhiFireRiskCoordinator(hass, entry, 58, 16)
        await coordinator.async_refresh()
        clock["now"] = datetime(2026, 9, 4, 21, 59, 59, tzinfo=UTC)
        pending = asyncio.create_task(coordinator._async_update_data())
        await delayed.requested.wait()
        clock["now"] = datetime(2026, 9, 4, 22, 0, 1, tzinfo=UTC)
        delayed.release.set()
        with pytest.raises(UpdateFailed, match="stale"):
            await pending
        await coordinator.async_shutdown()
