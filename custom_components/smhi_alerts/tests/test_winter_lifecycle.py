"""Winter forecasts through real HA setup, options, reload and unload."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts import _winter_settings
from custom_components.smhi_alerts.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

WINTER_POINT = {
    "valid_time": "2026-10-22T18:00:00+00:00",
    "precipitation_type": "snow",
    "precipitation_type_code": 5,
    "frozen_probability": 75,
    "temperature": -1.5,
}
WINTER_DATA = {
    "created_time": "2026-10-22T17:15:00+00:00",
    "reference_time": "2026-10-22T17:00:00+00:00",
    "current": WINTER_POINT,
    "forecast": [WINTER_POINT],
    "grid_latitude": 58,
    "grid_longitude": 16,
    "data_source_url": "https://opendata-download-metfcst.smhi.se/",
    "source_kind": "local_winter_forecast",
}


@pytest.fixture
def sources():
    with (
        patch(
            "custom_components.smhi_alerts.async_setup_frontend", new_callable=AsyncMock
        ),
        patch(
            "custom_components.smhi_alerts.sensor.SmhiAlertCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value={
                "state": "Varning",
                "attributes": {"warnings_count": 1, "highest_severity": "YELLOW"},
            },
        ),
        patch(
            "custom_components.smhi_alerts.thunder.SmhiThunderCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value={"current": {"probability": 25}, "forecast": []},
        ),
        patch(
            "custom_components.smhi_alerts.winter.SmhiWinterCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=deepcopy(WINTER_DATA),
        ) as winter,
    ):
        yield winter


async def setup_entry(hass, *, enabled=True, thunder=False, thunder_location=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Winter test",
        version=4,
        data={"mode": "district", "district": "14", "language": "sv"},
        options={
            "winter_enabled": enabled,
            "winter_location": {"latitude": 58, "longitude": 16},
            "thunder_probability_enabled": thunder,
            "thunder_probability_location": thunder_location
            or {"latitude": 58, "longitude": 16},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass, entry, suffix):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert entity_id is not None
    return hass.states.get(entity_id)


async def test_winter_disabled_preserves_existing_setup_without_download(hass, sources):
    entry = await setup_entry(hass, enabled=False, thunder=True)
    sources.assert_not_called()
    assert entry.runtime_data.winter is None
    assert (
        len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 3
    )
    assert state(hass, entry, "thunder_probability").state == "25"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_three_forecast_sensors_preserve_semantics_and_warning_state(
    hass, sources
):
    entry = await setup_entry(hass)
    expected = {
        "winter_precipitation_type": "snow",
        "winter_frozen_probability": "75",
        "winter_temperature": "-1.5",
    }
    for suffix, value in expected.items():
        entity = state(hass, entry, suffix)
        assert entity.state == value
        assert entity.attributes["source_kind"] == "local_winter_forecast"
        assert entity.attributes["valid_time"] == WINTER_POINT["valid_time"]
        assert entity.attributes["forecast"] == WINTER_DATA["forecast"]
        assert "state_class" not in entity.attributes
    assert (
        state(hass, entry, "winter_precipitation_type").attributes["device_class"]
        == "enum"
    )
    assert (
        state(hass, entry, "winter_frozen_probability").attributes[
            "unit_of_measurement"
        ]
        == "%"
    )
    assert (
        state(hass, entry, "winter_temperature").attributes["unit_of_measurement"]
        == "°C"
    )
    warning = state(hass, entry, "smhi_alert_sensor")
    assert warning.state == "Varning"
    assert warning.attributes["highest_severity"] == "YELLOW"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_initial_failure_isolated_from_thunder_and_warnings_then_recovers(
    hass, sources
):
    sources.side_effect = [UpdateFailed("Unavailable"), deepcopy(WINTER_DATA)]
    entry = await setup_entry(hass, thunder=True)
    for suffix in (
        "winter_precipitation_type",
        "winter_frozen_probability",
        "winter_temperature",
    ):
        entity = state(hass, entry, suffix)
        assert entity.state == "unavailable"
        assert entity.attributes["source_kind"] == "local_winter_forecast"
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert state(hass, entry, "thunder_probability").state == "25"
    await entry.runtime_data.winter.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, entry, "winter_precipitation_type").state == "snow"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_zero_and_unknown_values_are_distinct(hass, sources):
    entry = await setup_entry(hass)
    for value, expected in [(0, "0"), (None, "unknown")]:
        data = deepcopy(WINTER_DATA)
        data["current"]["frozen_probability"] = value
        data["current"]["temperature"] = value
        data["current"]["precipitation_type"] = "none" if value == 0 else None
        sources.return_value = data
        await entry.runtime_data.winter.async_refresh()
        await hass.async_block_till_done()
        assert state(hass, entry, "winter_frozen_probability").state == expected
        assert state(hass, entry, "winter_temperature").state == expected
        assert state(hass, entry, "winter_precipitation_type").state == (
            "none" if value == 0 else "unknown"
        )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_toggle_location_and_reload_keep_ids_and_clean_old_coordinators(
    hass, sources
):
    entry = await setup_entry(hass, enabled=False)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "winter_enabled": True}
    )
    await hass.async_block_till_done()
    ids = [
        state(hass, entry, suffix).entity_id
        for suffix in (
            "winter_precipitation_type",
            "winter_frozen_probability",
            "winter_temperature",
        )
    ]
    first = entry.runtime_data.winter
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, "winter_location": {"latitude": 59, "longitude": 17}},
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.winter is not first
    assert first._shutdown_requested
    assert not list(first.async_contexts())
    assert [
        state(hass, entry, suffix).entity_id
        for suffix in (
            "winter_precipitation_type",
            "winter_frozen_probability",
            "winter_temperature",
        )
    ] == ids
    second = entry.runtime_data.winter
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "winter_enabled": False}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.winter is None
    assert second._shutdown_requested
    sources.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    sources.assert_not_called()
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("same_point", [True, False])
async def test_same_point_shares_snow_download_client_only(hass, sources, same_point):
    entry = await setup_entry(
        hass,
        thunder=True,
        thunder_location={"latitude": 58 if same_point else 59, "longitude": 16},
    )
    assert (
        entry.runtime_data.thunder._client is entry.runtime_data.winter._client
    ) is same_point
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "location",
    [
        None,
        {},
        {"latitude": True, "longitude": 16},
        {"latitude": float("nan"), "longitude": 16},
        {"latitude": 91, "longitude": 16},
    ],
)
def test_invalid_winter_point_does_not_use_other_source_locations(location):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "winter_enabled": True,
            "winter_location": location,
            "thunder_probability_location": {"latitude": 58, "longitude": 16},
        },
    )
    assert _winter_settings(entry) == (True, None, None)
