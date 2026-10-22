"""Winter parsing, shared SNOW transport, local boundaries and failure behavior."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.snow import (
    SNOW_CREATED_TIME_URL,
    SNOW_UPDATE_INTERVAL,
    SmhiSnowClient,
)
from custom_components.smhi_alerts.thunder import SmhiThunderCoordinator, parse_thunder
from custom_components.smhi_alerts.winter import (
    PRECIPITATION_TYPES,
    WINTER_PARAMETERS,
    SmhiWinterCoordinator,
    parse_winter,
)


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status = status
        self.headers = {}

    async def __aenter__(self):
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


NOW = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)


@pytest.fixture
def payload():
    """Representative point response with independent winter and thunder fields."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "winter_point.json").read_text()
    )


def metadata(payload):
    return {key: payload[key] for key in ("createdTime", "referenceTime")}


def test_winter_scales_fraction_and_preserves_native_temperature(payload):
    result = parse_winter(payload, NOW)
    assert result["current"] == {
        "valid_time": "2026-10-22T16:00:00+00:00",
        "precipitation_type": "none",
        "precipitation_type_code": 0,
        "frozen_probability": 1.0,
        "temperature": 10.0,
    }
    assert result["temperature_unit"] == "°C"
    assert result["probability_unit"] == "%"
    assert result["source_kind"] == "local_winter_forecast"
    assert result["grid_latitude"] == 58.008376
    assert result["forecast"][0] == result["current"]
    assert "intervalParametersStartTime" not in result["current"]
    # The shared raw payload still gives thunder's original percent value.
    assert parse_thunder(payload, NOW)["current"]["probability"] == 6


@pytest.mark.parametrize("code", range(13))
def test_all_official_precipitation_types_have_distinct_enum_states(payload, code):
    payload["timeSeries"][0]["data"]["predominant_precipitation_type_at_surface"] = code
    current = parse_winter(payload, NOW)["current"]
    assert current["precipitation_type"] == PRECIPITATION_TYPES[code]
    assert current["precipitation_type_code"] == code
    assert len(set(PRECIPITATION_TYPES)) == 13


@pytest.mark.parametrize(
    ("field", "output", "values"),
    [
        (
            "probability_of_frozen_precipitation",
            "frozen_probability",
            [9999, -1, -9, 1.01, 100, True, "0.8", None, float("nan"), float("inf")],
        ),
        (
            "predominant_precipitation_type_at_surface",
            "precipitation_type",
            [9999, -1, 13, 5.5, True, "5", None, float("nan"), float("inf")],
        ),
        (
            "air_temperature",
            "temperature",
            [9999, True, "-2", None, float("nan"), float("inf")],
        ),
    ],
)
def test_invalid_fields_stay_unknown_without_hiding_other_values(
    payload, field, output, values
):
    for value in values:
        payload["timeSeries"][0]["data"][field] = value
        current = parse_winter(payload, NOW)["current"]
        assert current[output] is None
        assert current["valid_time"] == "2026-10-22T16:00:00+00:00"
        if field != "air_temperature":
            assert current["temperature"] == 10
        if field == "predominant_precipitation_type_at_surface":
            assert current["precipitation_type_code"] is None


@pytest.mark.parametrize(
    ("fraction", "percent"), [(0, 0), (0.01, 1), (0.5, 50), (1, 100)]
)
def test_probability_zero_and_fraction_are_meaningful(payload, fraction, percent):
    payload["timeSeries"][0]["data"].update(
        {"probability_of_frozen_precipitation": fraction, "air_temperature": 0}
    )
    current = parse_winter(payload, NOW)["current"]
    assert current["frozen_probability"] == percent
    assert current["temperature"] == 0


@pytest.mark.parametrize("values", [None, [], {}, {"tstm": 50}])
def test_missing_current_record_is_retained_without_skipping_to_later_known(
    payload, values
):
    payload["timeSeries"][0]["data"] = values
    result = parse_winter(payload, NOW)
    assert result["current"]["precipitation_type"] is None
    assert result["current"]["frozen_probability"] is None
    assert result["current"]["temperature"] is None
    assert result["forecast"][1]["temperature"] == 9.6


def test_exact_time_boundary_window_and_conflicting_duplicates(payload):
    original = deepcopy(payload["timeSeries"][1])
    payload["timeSeries"].reverse()
    duplicate = deepcopy(original)
    duplicate["data"]["air_temperature"] = -5
    payload["timeSeries"].extend([duplicate, original])
    payload["timeSeries"].append(
        {
            "time": (NOW + timedelta(hours=49)).isoformat(),
            "data": {"air_temperature": 99},
        }
    )
    result = parse_winter(payload, datetime(2026, 10, 22, 16, tzinfo=UTC))
    assert result["current"]["valid_time"].startswith("2026-10-22T17")
    assert result["current"]["temperature"] is None
    assert result["current"]["frozen_probability"] == 1
    assert len(result["forecast"]) == 2


@pytest.mark.parametrize(
    "created",
    [
        None,
        "invalid",
        "2026-10-22T15:00:00",
        "2026-10-22T13:30:00Z",
        "2026-10-22T15:46:00Z",
    ],
)
def test_invalid_expired_or_future_source_is_unavailable(payload, created):
    payload["createdTime"] = created
    with pytest.raises(UpdateFailed):
        parse_winter(payload, NOW)


async def test_shared_snow_clients_reuse_superset_download_and_metadata(payload):
    session = FakeSession(FakeResponse(payload), FakeResponse(metadata(payload)))
    client = SmhiSnowClient(
        session,
        58,
        12,
        parameters=("thunderstorm_probability", *WINTER_PARAMETERS),
        cache_interval=SNOW_UPDATE_INTERVAL,
    )
    first, second = await asyncio.gather(
        client.async_get_payload(NOW),
        client.async_get_payload(NOW + timedelta(microseconds=1)),
    )
    assert first is second
    assert len(session.urls) == 1
    assert all(parameter in session.urls[0] for parameter in WINTER_PARAMETERS)
    assert "thunderstorm_probability" in session.urls[0]
    assert parse_thunder(first, NOW)["current"]["probability"] == 6
    assert parse_winter(second, NOW)["current"]["frozen_probability"] == 1
    await asyncio.gather(
        client.async_get_payload(NOW + timedelta(minutes=15)),
        client.async_get_payload(NOW + timedelta(minutes=15, microseconds=1)),
    )
    assert session.urls[1] == SNOW_CREATED_TIME_URL
    assert len(session.urls) == 2


async def test_separate_locations_have_separate_point_data(payload):
    session = FakeSession(FakeResponse(payload), FakeResponse(payload))
    first = SmhiSnowClient(session, 58, 12, parameters=WINTER_PARAMETERS)
    second = SmhiSnowClient(session, 59, 13, parameters=WINTER_PARAMETERS)
    await first.async_get_payload(NOW)
    await second.async_get_payload(NOW)
    assert len(session.urls) == 2
    assert session.urls[0] != session.urls[1]


async def test_winter_only_does_not_require_thunder_parameter(hass, payload):
    for row in payload["timeSeries"]:
        row["data"].pop("thunderstorm_probability")
    session = FakeSession(FakeResponse(payload))
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    client = SmhiSnowClient(session, 58, 12, parameters=WINTER_PARAMETERS)
    with patch("custom_components.smhi_alerts.winter.dt_util.utcnow", return_value=NOW):
        coordinator = SmhiWinterCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        assert coordinator.data["current"]["temperature"] == 10
        assert "thunderstorm_probability" not in session.urls[0]
        await coordinator.async_shutdown()


async def test_shared_coordinators_share_fetch_with_independent_parsers(hass, payload):
    session = FakeSession(FakeResponse(payload))
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    client = SmhiSnowClient(
        session,
        58,
        12,
        parameters=("thunderstorm_probability", *WINTER_PARAMETERS),
        cache_interval=SNOW_UPDATE_INTERVAL,
    )
    with (
        patch("custom_components.smhi_alerts.winter.dt_util.utcnow", return_value=NOW),
        patch("custom_components.smhi_alerts.winter.async_track_point_in_utc_time"),
        patch("custom_components.smhi_alerts.thunder.async_track_point_in_utc_time"),
    ):
        winter = SmhiWinterCoordinator(hass, entry, 58, 12, client=client)
        thunder = SmhiThunderCoordinator(hass, entry, 58, 12, client=client)
        await asyncio.gather(winter.async_refresh(), thunder.async_refresh())
        assert len(session.urls) == 1
        assert winter.data["current"]["frozen_probability"] == 1
        assert thunder.data["current"]["probability"] == 6
        await winter.async_shutdown()
        await thunder.async_shutdown()


async def test_local_timer_advances_then_expires_without_download(hass, payload):
    session = FakeSession(FakeResponse(payload))
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    client = SmhiSnowClient(session, 58, 12, parameters=WINTER_PARAMETERS)
    with (
        patch("custom_components.smhi_alerts.winter.dt_util.utcnow", return_value=NOW),
        patch(
            "custom_components.smhi_alerts.winter.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiWinterCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        assert track.call_args.args[2] == datetime(2026, 10, 22, 16, tzinfo=UTC)
        coordinator._async_boundary(datetime(2026, 10, 22, 16, tzinfo=UTC))
        assert coordinator.data["current"]["temperature"] == 9.6
        coordinator._async_boundary(datetime(2026, 10, 22, 17, 29, 14, tzinfo=UTC))
        assert not coordinator.last_update_success
        assert len(session.urls) == 1
        await coordinator.async_shutdown()
        assert coordinator._unsub_boundary is None


async def test_failure_does_not_resurrect_cached_data_and_retry_recovers(hass, payload):
    session = FakeSession(
        FakeResponse(payload), FakeResponse(status=503), FakeResponse(metadata(payload))
    )
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    client = SmhiSnowClient(session, 58, 12, parameters=WINTER_PARAMETERS)
    with patch("custom_components.smhi_alerts.winter.dt_util.utcnow", return_value=NOW):
        coordinator = SmhiWinterCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        coordinator._async_boundary(NOW + timedelta(minutes=30))
        assert not coordinator.last_update_success
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        await coordinator.async_shutdown()


async def test_response_expiring_during_io_stays_unavailable(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    delayed = DelayedResponse(payload)
    session = FakeSession(delayed)
    client = SmhiSnowClient(session, 58, 12, parameters=WINTER_PARAMETERS)
    clock = {"now": datetime(2026, 10, 22, 17, 29, 13, tzinfo=UTC)}
    with patch(
        "custom_components.smhi_alerts.winter.dt_util.utcnow",
        side_effect=lambda: clock["now"],
    ):
        coordinator = SmhiWinterCoordinator(hass, entry, 58, 12, client=client)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        clock["now"] += timedelta(seconds=2)
        delayed.release.set()
        await pending
        assert not coordinator.last_update_success
        await coordinator.async_shutdown()
