"""SNOW gust selection, complete maxima and forecast lifecycle regressions."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.precipitation import (
    PRECIPITATION_PARAMETERS,
    SmhiPrecipitationCoordinator,
)
from custom_components.smhi_alerts.snow import (
    SNOW_CREATED_TIME_URL,
    SNOW_UPDATE_INTERVAL,
    SmhiSnowClient,
)
from custom_components.smhi_alerts.wind import (
    WIND_PARAMETERS,
    SmhiWindCoordinator,
    parse_wind,
)
from custom_components.smhi_alerts.wind_sensor import (
    SmhiWindGustSensor,
    SmhiWindMaxSensor,
)

NOW = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)


@pytest.fixture
def payload():
    """Representative SNOW timeline exercising source coverage beyond 24/48h."""
    return json.loads(
        (
            Path(__file__).parent / "fixtures" / "wind_precipitation_point.json"
        ).read_text()
    )


class Response:
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


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_next_actual_gust_and_maximum_do_not_include_bracketing_value(payload):
    data = parse_wind(payload, NOW)
    assert data["current"] == {"valid_time": "2026-10-22T16:00:00+00:00", "gust": 7.3}
    assert len(data["forecast"]) == 48
    assert data["wind_unit"] == "m/s"
    assert data["source_kind"] == "local_wind_forecast"
    assert data["max_complete"]
    assert data["max_gust_24h"] == 22
    assert data["max_gust_time"] == "2026-10-22T22:00:00+00:00"  # earliest tie
    assert data["max_window_end"] == "2026-10-23T15:30:00+00:00"
    assert data["forecast"][24]["gust"] == 80  # outside the next-24h maximum


@pytest.mark.parametrize(
    "value", [None, True, "10", 9999, -1, float("nan"), float("inf")]
)
def test_nearest_missing_gust_remains_unknown_and_blocks_partial_max(payload, value):
    payload["timeSeries"][0]["data"]["wind_speed_of_gust"] = value
    data = parse_wind(payload, NOW)
    assert data["current"]["gust"] is None
    assert data["forecast"][1]["gust"] is not None
    assert not data["max_complete"]
    assert data["max_gust_24h"] is data["max_gust_time"] is None


def test_zero_gust_is_valid_for_next_value_and_complete_max(payload):
    for row in payload["timeSeries"]:
        row["data"]["wind_speed_of_gust"] = 0
    data = parse_wind(payload, NOW)
    assert data["current"]["gust"] == 0
    assert data["max_complete"]
    assert data["max_gust_24h"] == 0


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "short_window",
        "coarse",
        "missing_value",
        "conflicting_duplicate",
        "bad_time",
    ],
)
def test_incomplete_windows_never_underestimate_as_complete_maximum(payload, change):
    if change == "gap":
        del payload["timeSeries"][4]
    elif change == "short_window":
        payload["timeSeries"] = payload["timeSeries"][:24]
    elif change == "coarse":
        payload["timeSeries"] = payload["timeSeries"][::3]
    elif change == "missing_value":
        del payload["timeSeries"][10]["data"]["wind_speed_of_gust"]
    elif change == "conflicting_duplicate":
        row = deepcopy(payload["timeSeries"][10])
        row["data"]["wind_speed_of_gust"] = 99
        payload["timeSeries"].append(row)
        payload["timeSeries"].append(deepcopy(payload["timeSeries"][10]))
    elif change == "bad_time":
        payload["timeSeries"].append(
            {"time": "broken", "data": {"wind_speed_of_gust": 30}}
        )
    data = parse_wind(payload, NOW)
    assert not data["max_complete"]
    assert data["max_gust_24h"] is None
    assert data["current"]["gust"] == 7.3


def test_local_boundary_advances_next_time_and_rolls_max_window(payload):
    data = parse_wind(payload, datetime(2026, 10, 22, 16, tzinfo=UTC))
    assert data["current"]["valid_time"] == "2026-10-22T17:00:00+00:00"
    assert data["max_complete"]
    assert data["max_gust_24h"] == 80
    assert data["max_gust_time"] == "2026-10-23T16:00:00+00:00"


@pytest.mark.parametrize(
    "created", [None, "invalid", "2026-10-22T13:30:00Z", "2026-10-22T15:46:00Z"]
)
def test_invalid_stale_or_future_source_is_rejected(payload, created):
    payload["createdTime"] = created
    with pytest.raises(UpdateFailed):
        parse_wind(payload, NOW)


async def test_shared_wind_precipitation_point_and_metadata_only_download_once(
    hass, payload
):
    session = Session(
        Response(payload), Response({"createdTime": payload["createdTime"]})
    )
    client = SmhiSnowClient(
        session,
        58,
        12,
        parameters=(*WIND_PARAMETERS, *PRECIPITATION_PARAMETERS),
        cache_interval=SNOW_UPDATE_INTERVAL,
    )
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    clock = {"now": NOW}
    with (
        patch(
            "custom_components.smhi_alerts.wind.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
        patch("custom_components.smhi_alerts.wind.async_track_point_in_utc_time"),
        patch(
            "custom_components.smhi_alerts.precipitation.async_track_point_in_utc_time"
        ),
    ):
        wind = SmhiWindCoordinator(hass, entry, 58, 12, client=client)
        precipitation = SmhiPrecipitationCoordinator(hass, entry, 58, 12, client=client)
        await asyncio.gather(wind.async_refresh(), precipitation.async_refresh())
        assert wind.data["current"]["gust"] == 7.3
        assert precipitation.data["current"]["amount"] == 0
        assert len(session.urls) == 1
        clock["now"] += timedelta(minutes=15)
        await asyncio.gather(wind.async_refresh(), precipitation.async_refresh())
        assert len(session.urls) == 2
        assert session.urls[1] == SNOW_CREATED_TIME_URL
        await wind.async_shutdown()
        await precipitation.async_shutdown()


async def test_wind_timer_rolls_max_then_expires_without_download(hass, payload):
    session = Session(Response(payload))
    client = SmhiSnowClient(session, 58, 12, parameters=WIND_PARAMETERS)
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    with (
        patch("custom_components.smhi_alerts.wind.dt_util.utcnow", return_value=NOW),
        patch(
            "custom_components.smhi_alerts.wind.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiWindCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        assert track.call_args.args[2] == datetime(2026, 10, 22, 16, tzinfo=UTC)
        coordinator._async_boundary(datetime(2026, 10, 22, 16, tzinfo=UTC))
        assert coordinator.data["max_gust_24h"] == 80
        coordinator._async_boundary(datetime(2026, 10, 22, 17, 29, 14, tzinfo=UTC))
        assert not coordinator.last_update_success
        assert len(session.urls) == 1
        await coordinator.async_shutdown()
        assert coordinator._unsub_boundary is None


async def test_wind_outage_cannot_be_resurrected_by_timer_and_recovers(hass, payload):
    session = Session(
        Response(payload),
        Response(status=503),
        Response({"createdTime": payload["createdTime"]}),
    )
    client = SmhiSnowClient(session, 58, 12, parameters=WIND_PARAMETERS)
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    with (
        patch("custom_components.smhi_alerts.wind.dt_util.utcnow", return_value=NOW),
        patch("custom_components.smhi_alerts.wind.async_track_point_in_utc_time"),
    ):
        coordinator = SmhiWindCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        gust = SmhiWindGustSensor(coordinator, entry)
        maximum = SmhiWindMaxSensor(coordinator, entry)
        assert gust.native_value == 7.3
        assert maximum.native_value == 22
        assert (
            maximum.extra_state_attributes["valid_time"]
            == coordinator.data["max_gust_time"]
        )
        assert gust.capability_attributes["wind_unit"] == "m/s"
        assert gust.state_class is None
        assert maximum.state_class is None
        await coordinator.async_refresh()
        assert not gust.available
        coordinator._async_boundary(datetime(2026, 10, 22, 16, tzinfo=UTC))
        assert not gust.available
        await coordinator.async_refresh()
        assert gust.available
        await coordinator.async_shutdown()
