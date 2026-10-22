"""Station observations preserve provenance, quality, freshness and missingness."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientError
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.snow_depth import (
    SNOW_DEPTH_MAX_AGE,
    SmhiSnowDepthClient,
    SmhiSnowDepthCoordinator,
    async_get_snow_stations,
    parse_snow_depth,
)
from custom_components.smhi_alerts.snow_depth_sensor import SmhiSnowDepthSensor

NOW = datetime(2026, 10, 22, 17, tzinfo=UTC)
OBSERVED = datetime(2026, 10, 22, 6, tzinfo=UTC)


@pytest.fixture
def payload():
    """Actual bounded Askim parameter52 response retrieved 22 October2026."""
    return json.loads(
        (Path(__file__).parent / "fixtures" / "snow_depth_askim.json").read_text()
    )


class Response:
    def __init__(self, payload=None, status=200, error=None):
        self.payload = payload
        self.status = status
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
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


def parse(payload, now=NOW):
    return parse_snow_depth(payload, "72620", "52", now, latitude=57.7, longitude=12)


def test_real_minute_catalogue_response_has_actual_daily_measurement_time(payload):
    data = parse(payload)
    assert data["depth_cm"] == 0
    assert data["station_id"] == "72620"
    assert data["station_name"] == "Askim D"
    assert data["parameter"] == "52"
    assert data["observation_time"] == OBSERVED.isoformat()
    assert data["expires_at"] == (OBSERVED + SNOW_DEPTH_MAX_AGE).isoformat()
    assert data["quality"] == "G"
    assert data["snow_cover"] is None
    assert data["distance_km"] > 0
    assert not data["stale"]


@pytest.mark.parametrize(
    ("value", "depth", "cover"),
    [
        ("0", 0, None),
        ("0.12", 12, None),
        ("3", 300, None),
        ("-0.01", None, "trace"),
        ("-0.02", None, "patchy"),
        ("-0.03", None, None),
        ("9999", None, None),
        ("3.01", None, None),
        (None, None, None),
        (True, None, None),
        ("nan", None, None),
        ("inf", None, None),
        ("invalid", None, None),
    ],
)
def test_numeric_depth_and_special_cover_codes_are_distinct(
    payload, value, depth, cover
):
    payload["value"][0]["value"] = value
    data = parse(payload)
    assert data["depth_cm"] == depth
    assert data["snow_cover"] == cover


@pytest.mark.parametrize("quality", ["Y", None, "", "invalid"])
def test_unchecked_suspect_or_missing_quality_preserved_without_approved_depth(
    payload, quality
):
    payload["value"][0].update(value="0.12", quality=quality)
    data = parse(payload)
    assert data["depth_cm"] is None
    assert data["quality"] == quality
    assert data["observation_time"] == OBSERVED.isoformat()


def test_latest_missing_value_never_replaced_by_older_known_depth(payload):
    payload["value"] = [
        {
            "date": int((OBSERVED - timedelta(hours=1)).timestamp() * 1000),
            "value": "0.15",
            "quality": "G",
        },
        {"date": int(OBSERVED.timestamp() * 1000), "value": None, "quality": "G"},
    ]
    assert parse(payload)["depth_cm"] is None
    assert parse(payload)["observation_time"] == OBSERVED.isoformat()


def test_conflicting_same_time_values_or_quality_stay_unknown(payload):
    first = deepcopy(payload["value"][0])
    payload["value"].extend([{**first, "value": "0.12"}, first])
    assert parse(payload)["depth_cm"] is None
    payload["value"] = [first, {**first, "quality": "Y"}]
    assert parse(payload)["depth_cm"] is None
    assert parse(payload)["quality"] == "conflicting"


def test_fresh_metadata_cannot_revive_stale_measurement(payload):
    now = OBSERVED + SNOW_DEPTH_MAX_AGE
    payload["updated"] = int(now.timestamp() * 1000)
    data = parse(payload, now)
    assert data["stale"]
    assert data["depth_cm"] is None
    assert data["observation_time"] == OBSERVED.isoformat()


@pytest.mark.parametrize(
    "change",
    [
        "wrong_station",
        "wrong_parameter",
        "wrong_unit",
        "empty",
        "missing_dates",
        "future",
    ],
)
def test_invalid_or_mismatched_sources_rejected(payload, change):
    if change == "wrong_station":
        payload["station"]["key"] = "12345"
    elif change == "wrong_parameter":
        payload["parameter"]["key"] = "8"
    elif change == "wrong_unit":
        payload["parameter"]["unit"] = "cm"
    elif change == "empty":
        payload["value"] = []
    elif change == "missing_dates":
        payload["value"][0]["date"] = "2026-10-22"
    elif change == "future":
        payload["value"][0]["date"] = int((NOW + timedelta(hours=1)).timestamp() * 1000)
    with pytest.raises(UpdateFailed):
        parse(payload)


async def test_daily_parameter_special_codes_work_without_fallback(payload):
    payload["parameter"]["key"] = "8"
    payload["value"][0]["value"] = "-0.01"
    session = Session(Response(payload))
    client = SmhiSnowDepthClient(session, "72620", "8")
    data = await client.async_get_observation(NOW)
    assert data["snow_cover"] == "trace"
    assert data["depth_cm"] is None
    assert len(session.urls) == 1
    assert "/parameter/8/" in session.urls[0]


@pytest.mark.parametrize(
    "response",
    [
        Response(status=503),
        Response(error=ClientError("bad request")),
        Response(error=TimeoutError()),
        Response([]),
    ],
)
async def test_client_recovers_from_transport_or_invalid_source(payload, response):
    session = Session(response, Response(payload))
    client = SmhiSnowDepthClient(session, "72620", "52")
    with pytest.raises(UpdateFailed):
        await client.async_get_observation(NOW)
    assert (await client.async_get_observation(NOW))["depth_cm"] == 0


async def test_stale_first_result_retains_station_time_and_quality(payload):
    client = SmhiSnowDepthClient(Session(Response(payload)), "72620", "52")
    with pytest.raises(UpdateFailed, match="stale"):
        await client.async_get_observation(OBSERVED + SNOW_DEPTH_MAX_AGE)
    assert client.last_data["observation_time"] == OBSERVED.isoformat()
    assert client.last_data["quality"] == "G"
    assert client.last_data["depth_cm"] is None


async def test_source_older_than_cached_observation_cannot_replace_it(payload):
    older = deepcopy(payload)
    older["value"][0]["date"] -= 3600000
    session = Session(Response(payload), Response(older))
    client = SmhiSnowDepthClient(session, "72620", "52")
    await client.async_get_observation(NOW)
    with pytest.raises(UpdateFailed, match="older"):
        await client.async_get_observation(NOW)
    assert client.last_data["observation_time"] == OBSERVED.isoformat()


async def test_catalogues_only_list_active_valid_stations_sorted_by_distance():
    stations = [
        {"key": "2", "name": "Far", "active": True, "latitude": 68, "longitude": 18},
        {"key": "1", "name": "Near", "active": True, "latitude": 57.7, "longitude": 12},
        {
            "key": "3",
            "name": "Inactive",
            "active": False,
            "latitude": 57.7,
            "longitude": 12,
        },
        {
            "key": "4",
            "name": "Invalid",
            "active": True,
            "latitude": True,
            "longitude": 12,
        },
    ]
    session = Session(
        Response({"key": "52", "summary": "minute catalogue", "station": stations}),
        Response({"key": "8", "summary": "daily catalogue", "station": stations}),
    )
    result = await async_get_snow_stations(session, 57.7, 12)
    assert [(row["station_id"], row["parameter"]) for row in result] == [
        ("1", "52"),
        ("1", "8"),
        ("2", "52"),
        ("2", "8"),
    ]
    assert result[0]["distance_km"] == 0
    assert result[0]["parameter_summary"] == "minute catalogue"
    assert len(session.urls) == 2  # no probing every station


async def test_one_catalogue_outage_can_use_other_without_silent_measurement_fallback():
    session = Session(
        Response(status=503),
        Response(
            {
                "key": "8",
                "station": [
                    {
                        "key": "1",
                        "name": "Station",
                        "active": True,
                        "latitude": 57.7,
                        "longitude": 12,
                    }
                ],
            }
        ),
    )
    result = await async_get_snow_stations(session, 57.7, 12)
    assert len(result) == 1
    assert result[0]["parameter"] == "8"


async def test_observation_expiry_and_outage_remove_current_depth_but_keep_provenance(
    hass, payload
):
    entry = MockConfigEntry(domain="smhi_alerts", data={})
    entry.add_to_hass(hass)
    session = Session(Response(payload), Response(status=503), Response(payload))
    clock = {"now": NOW}
    with (
        patch(
            "custom_components.smhi_alerts.snow_depth.aiohttp_client.async_get_clientsession",
            return_value=session,
        ),
        patch(
            "custom_components.smhi_alerts.snow_depth.dt_util.utcnow",
            side_effect=lambda: clock["now"],
        ),
        patch(
            "custom_components.smhi_alerts.snow_depth.async_track_point_in_utc_time"
        ) as track,
    ):
        coordinator = SmhiSnowDepthCoordinator(hass, entry, "72620", "52")
        sensor = SmhiSnowDepthSensor(coordinator, entry)
        before = sensor.capability_attributes.keys()
        await coordinator.async_refresh()
        assert sensor.native_value == 0
        assert track.call_args.args[2] == OBSERVED + SNOW_DEPTH_MAX_AGE
        await coordinator.async_refresh()
        assert not sensor.available
        assert sensor.native_value is None
        attrs = sensor.capability_attributes
        assert attrs["depth_cm"] is None
        assert attrs["station_name"] == "Askim D"
        assert attrs["observation_time"] == OBSERVED.isoformat()
        assert before == attrs.keys()
        await coordinator.async_refresh()
        assert sensor.available
        assert sensor.native_value == 0
        clock["now"] = OBSERVED + SNOW_DEPTH_MAX_AGE
        coordinator._async_expire(clock["now"])
        assert not sensor.available
        assert sensor.capability_attributes["stale"]
        assert sensor.native_value is None
        await coordinator.async_shutdown()
        assert coordinator._unsub_expiry is None
        assert len(session.urls) == 3
