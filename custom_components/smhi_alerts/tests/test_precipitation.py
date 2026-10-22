"""Precipitation probabilities and water totals retain exact source intervals."""

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
    parse_precipitation,
)
from custom_components.smhi_alerts.precipitation_sensor import (
    SmhiPrecipitationAmountSensor,
    SmhiPrecipitationProbabilitySensor,
)
from custom_components.smhi_alerts.snow import SmhiSnowClient

NOW = datetime(2026, 10, 22, 15, 30, tzinfo=UTC)


@pytest.fixture
def payload():
    """Representative full SNOW source timeline, with explicit period starts."""
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


class DelayedResponse(Response):
    def __init__(self, payload):
        super().__init__(payload)
        self.requested = asyncio.Event()
        self.release = asyncio.Event()

    async def json(self):
        self.requested.set()
        await self.release.wait()
        return await super().json()


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_zero_probabilities_and_amounts_are_valid_explicit_interval_totals(payload):
    data = parse_precipitation(payload, NOW)
    assert data["current"] == {
        "valid_time": "2026-10-22T16:00:00+00:00",
        "interval_start": "2026-10-22T15:00:00+00:00",
        "probability": 0,
        "amount": 0,
    }
    assert len(data["forecast"]) == 48
    assert data["amount_unit"] == "mm"
    assert data["probability_unit"] == "%"
    assert data["source_kind"] == "local_precipitation_forecast"


@pytest.mark.parametrize("hours", [1, 3, 6, 12])
def test_total_already_started_interval_not_divided_or_prorated(payload, hours):
    row = payload["timeSeries"][0]
    end = datetime.fromisoformat(row["time"])
    start = end - timedelta(hours=hours)
    row["intervalParametersStartTime"] = start.isoformat()
    row["data"].update(probability_of_precipitation=60, precipitation_amount_mean=12)
    current = parse_precipitation(payload, NOW)["current"]
    assert current["interval_start"] == start.isoformat()
    assert current["amount"] == 12
    assert current["probability"] == 60
    assert start < NOW  # even partially elapsed source intervals stay whole


@pytest.mark.parametrize(
    "start",
    [
        None,
        "invalid",
        "2026-10-22T15:00:00",
        "2026-10-22T16:00:00Z",
        "2026-10-22T17:00:00Z",
        "2026-10-20T16:00:00Z",
    ],
)
def test_missing_invalid_or_nonpositive_intervals_stay_unknown_at_same_time(
    payload, start
):
    payload["timeSeries"][0]["intervalParametersStartTime"] = start
    data = parse_precipitation(payload, NOW)
    assert data["current"]["valid_time"] == "2026-10-22T16:00:00+00:00"
    assert data["current"]["interval_start"] is None
    assert data["current"]["amount"] is None
    assert data["current"]["probability"] is None
    assert data["forecast"][1]["amount"] == 1.2


@pytest.mark.parametrize(
    "value", [None, True, "10", 9999, -1, float("nan"), float("inf")]
)
def test_invalid_amount_never_becomes_zero_or_hides_independent_probability(
    payload, value
):
    payload["timeSeries"][0]["data"]["precipitation_amount_mean"] = value
    current = parse_precipitation(payload, NOW)["current"]
    assert current["amount"] is None
    assert current["probability"] == 0
    assert current["interval_start"] is not None


@pytest.mark.parametrize(
    "value", [None, True, "10", 9999, -1, 101, float("nan"), float("inf")]
)
def test_invalid_probability_never_hides_independent_amount(payload, value):
    payload["timeSeries"][0]["data"]["probability_of_precipitation"] = value
    current = parse_precipitation(payload, NOW)["current"]
    assert current["probability"] is None
    assert current["amount"] == 0


def test_duplicate_conflicts_preserve_unambiguous_values_but_not_conflicting_periods(
    payload,
):
    row = deepcopy(payload["timeSeries"][0])
    different_amount = deepcopy(row)
    different_amount["data"]["precipitation_amount_mean"] = 5
    payload["timeSeries"].extend([different_amount, row])
    result = parse_precipitation(payload, NOW)["current"]
    assert result["probability"] == 0
    assert result["amount"] is None
    different_interval = deepcopy(row)
    different_interval["intervalParametersStartTime"] = "2026-10-22T13:00:00Z"
    payload["timeSeries"].append(different_interval)
    result = parse_precipitation(payload, NOW)["current"]
    assert result["interval_start"] is None
    assert result["probability"] is None
    assert result["amount"] is None


def test_unknown_current_does_not_skip_to_later_period_or_sum_overlaps(payload):
    payload["timeSeries"][0]["data"] = None
    next_row = payload["timeSeries"][1]
    next_row["intervalParametersStartTime"] = "2026-10-22T14:00:00Z"
    next_row["data"]["precipitation_amount_mean"] = 8
    result = parse_precipitation(payload, NOW)
    assert result["current"]["amount"] is None
    assert result["forecast"][1]["amount"] == 8
    advanced = parse_precipitation(payload, datetime(2026, 10, 22, 16, tzinfo=UTC))
    assert advanced["current"]["amount"] == 8
    assert advanced["current"]["interval_start"] == "2026-10-22T14:00:00+00:00"


@pytest.mark.parametrize(
    "created", [None, "invalid", "2026-10-22T13:30:00Z", "2026-10-22T15:46:00Z"]
)
def test_stale_or_invalid_forecast_source_rejected(payload, created):
    payload["createdTime"] = created
    with pytest.raises(UpdateFailed):
        parse_precipitation(payload, NOW)


async def test_precipitation_timer_advances_whole_interval_and_expires_source(
    hass, payload
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = Session(Response(payload))
    client = SmhiSnowClient(session, 58, 12, parameters=PRECIPITATION_PARAMETERS)
    with (
        patch(
            "custom_components.smhi_alerts.precipitation.dt_util.utcnow",
            return_value=NOW,
        ),
        patch(
            "custom_components.smhi_alerts.precipitation.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiPrecipitationCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        assert track.call_args.args[2] == datetime(2026, 10, 22, 16, tzinfo=UTC)
        coordinator._async_boundary(datetime(2026, 10, 22, 16, tzinfo=UTC))
        assert (
            coordinator.data["current"]["interval_start"] == "2026-10-22T16:00:00+00:00"
        )
        assert coordinator.data["current"]["amount"] == 1.2
        coordinator._async_boundary(datetime(2026, 10, 22, 17, 29, 14, tzinfo=UTC))
        assert not coordinator.last_update_success
        assert len(session.urls) == 1
        await coordinator.async_shutdown()
        assert coordinator._unsub_boundary is None


async def test_precipitation_sensors_preserve_native_units_and_interval_metadata(
    hass, payload
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    client = SmhiSnowClient(
        Session(Response(payload)), 58, 12, parameters=PRECIPITATION_PARAMETERS
    )
    with (
        patch(
            "custom_components.smhi_alerts.precipitation.dt_util.utcnow",
            return_value=NOW,
        ),
        patch(
            "custom_components.smhi_alerts.precipitation.async_track_point_in_utc_time"
        ),
    ):
        coordinator = SmhiPrecipitationCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        probability = SmhiPrecipitationProbabilitySensor(coordinator, entry)
        amount = SmhiPrecipitationAmountSensor(coordinator, entry)
        assert probability.native_value == 0
        assert amount.native_value == 0
        assert probability.native_unit_of_measurement == "%"
        assert amount.native_unit_of_measurement == "mm"
        assert amount.device_class == "precipitation"
        assert probability.state_class is amount.state_class is None
        assert (
            amount.extra_state_attributes["interval_start"]
            == "2026-10-22T15:00:00+00:00"
        )
        assert amount.capability_attributes["amount_unit"] == "mm"
        assert {"current", "forecast"} <= amount._unrecorded_attributes
        await coordinator.async_shutdown()


async def test_network_failure_not_resurrected_by_local_boundary_and_recovery(
    hass, payload
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = Session(
        Response(payload),
        Response(status=503),
        Response({"createdTime": payload["createdTime"]}),
    )
    client = SmhiSnowClient(session, 58, 12, parameters=PRECIPITATION_PARAMETERS)
    with (
        patch(
            "custom_components.smhi_alerts.precipitation.dt_util.utcnow",
            return_value=NOW,
        ),
        patch(
            "custom_components.smhi_alerts.precipitation.async_track_point_in_utc_time"
        ),
    ):
        coordinator = SmhiPrecipitationCoordinator(hass, entry, 58, 12, client=client)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        coordinator._async_boundary(datetime(2026, 10, 22, 16, tzinfo=UTC))
        assert not coordinator.last_update_success
        await coordinator.async_refresh()
        assert coordinator.last_update_success
        await coordinator.async_shutdown()


async def test_response_expiring_during_io_never_revives_source(hass, payload):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    delayed = DelayedResponse(payload)
    client = SmhiSnowClient(
        Session(delayed), 58, 12, parameters=PRECIPITATION_PARAMETERS
    )
    clock = {"now": datetime(2026, 10, 22, 17, 29, 13, tzinfo=UTC)}
    with (
        patch(
            "custom_components.smhi_alerts.precipitation.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
        patch(
            "custom_components.smhi_alerts.precipitation.async_track_point_in_utc_time"
        ),
    ):
        coordinator = SmhiPrecipitationCoordinator(hass, entry, 58, 12, client=client)
        pending = asyncio.create_task(coordinator.async_refresh())
        await delayed.requested.wait()
        clock["now"] += timedelta(seconds=2)
        delayed.release.set()
        await pending
        assert not coordinator.last_update_success
        await coordinator.async_shutdown()
