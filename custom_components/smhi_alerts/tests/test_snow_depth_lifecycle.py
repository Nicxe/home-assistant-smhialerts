"""Station observations coexist with forecasts through HA entry lifecycle."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts import _snow_depth_settings
from custom_components.smhi_alerts.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture
def observation():
    now = dt_util.utcnow()
    return {
        "depth_cm": 5.0,
        "station_id": "72620",
        "station_name": "Askim D",
        "station_latitude": 57.6284,
        "station_longitude": 11.9618,
        "distance_km": 8.0,
        "observation_time": now.isoformat(),
        "quality": "G",
        "snow_cover": None,
        "parameter": "8",
        "source_url": "https://opendata-download-metobs.smhi.se/",
        "expires_at": (now + timedelta(hours=36)).isoformat(),
        "stale": False,
    }


@pytest.fixture
def sources(observation):
    with (
        patch(
            "custom_components.smhi_alerts.async_setup_frontend", new_callable=AsyncMock
        ),
        patch(
            "custom_components.smhi_alerts.sensor.SmhiAlertCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value={"state": "Varning", "attributes": {"warnings_count": 1}},
        ),
        patch(
            "custom_components.smhi_alerts.winter.SmhiWinterCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value={
                "current": {
                    "temperature": -1,
                    "precipitation_type": "snow",
                    "frozen_probability": 80,
                },
                "forecast": [],
            },
        ),
        patch(
            "custom_components.smhi_alerts.snow_depth.SmhiSnowDepthCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=deepcopy(observation),
        ) as source,
    ):
        yield source


async def setup_entry(hass, *, enabled=True):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Snow station",
        version=4,
        data={"mode": "district", "district": "14", "language": "sv"},
        options={
            "snow_depth_enabled": enabled,
            "snow_depth_station": "72620",
            "snow_depth_parameter": "8",
            "winter_enabled": True,
            "winter_location": {"latitude": 58, "longitude": 16},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass, entry, suffix="snow_depth"):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert entity_id
    return hass.states.get(entity_id)


async def test_disabled_station_never_downloads(hass, sources):
    entry = await setup_entry(hass, enabled=False)
    sources.assert_not_called()
    assert entry.runtime_data.snow_depth is None
    assert state(hass, entry, "winter_temperature").state == "-1"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_observation_sensor_uses_cm_and_exact_source_metadata(
    hass, sources, observation
):
    entry = await setup_entry(hass)
    entity = state(hass, entry)
    assert float(entity.state) == 5
    assert entity.attributes["unit_of_measurement"] == "cm"
    assert entity.attributes["source_kind"] == "snow_depth_observation"
    assert entity.attributes["observation_time"] == observation["observation_time"]
    assert entity.attributes["station_id"] == "72620"
    assert entity.attributes["quality"] == "G"
    assert state(hass, entry, "winter_temperature").state == "-1"
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_observation_outage_isolated_and_recovers(hass, sources, observation):
    sources.side_effect = [UpdateFailed("Unavailable"), deepcopy(observation)]
    entry = await setup_entry(hass)
    assert state(hass, entry).state == "unavailable"
    assert state(hass, entry).attributes["source_kind"] == "snow_depth_observation"
    assert state(hass, entry, "winter_temperature").state == "-1"
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    await entry.runtime_data.snow_depth.async_refresh()
    await hass.async_block_till_done()
    assert float(state(hass, entry).state) == 5
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unknown_and_zero_not_conflated_and_failure_does_not_expose_cached_depth(
    hass, sources, observation
):
    entry = await setup_entry(hass)
    for value, expected in [(0, "0"), (None, "unknown")]:
        data = deepcopy(observation)
        data["depth_cm"] = value
        sources.return_value = data
        await entry.runtime_data.snow_depth.async_refresh()
        await hass.async_block_till_done()
        assert state(hass, entry).state == expected
    sources.return_value = deepcopy(observation)
    await entry.runtime_data.snow_depth.async_refresh()
    sources.side_effect = UpdateFailed("Unavailable")
    await entry.runtime_data.snow_depth.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, entry).state == "unavailable"
    assert state(hass, entry).attributes.get("depth_cm") is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_switch_station_source_and_toggle_preserves_identity_and_stops_old_sources(
    hass, sources
):
    entry = await setup_entry(hass)
    entity_id = state(hass, entry).entity_id
    first = entry.runtime_data.snow_depth
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "snow_depth_station": "72560",
            "snow_depth_parameter": "52",
        },
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.snow_depth is not first
    assert first._shutdown_requested
    assert not list(first.async_contexts())
    assert state(hass, entry).entity_id == entity_id
    second = entry.runtime_data.snow_depth
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "snow_depth_enabled": False}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.snow_depth is None
    assert second._shutdown_requested
    sources.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    sources.assert_not_called()
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "snow_depth_enabled": True}
    )
    await hass.async_block_till_done()
    assert state(hass, entry).entity_id == entity_id
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "station,parameter",
    [(None, "8"), ("../test", "8"), (True, "8"), ("72620", "unsupported")],
)
def test_invalid_saved_station_never_substitutes_home_location(station, parameter):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "snow_depth_enabled": True,
            "snow_depth_station": station,
            "snow_depth_parameter": parameter,
        },
    )
    assert _snow_depth_settings(entry) == (True, None, None)
