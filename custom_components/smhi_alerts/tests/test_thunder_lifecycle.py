"""Exercise optional thunder probability through real HA config entries."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts import _thunder_settings
from custom_components.smhi_alerts.const import (
    CONF_THUNDER_PROBABILITY_ENABLED,
    CONF_THUNDER_PROBABILITY_LOCATION,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

WARNING_DATA = {
    "state": "Varning",
    "attributes": {
        "messages": [],
        "warnings_count": 1,
        "messages_count": 0,
        "alerts_count": 1,
        "highest_severity": "YELLOW",
    },
}
FIRE_DATA = {"current": {"forest_fire_risk": "high"}, "forecast": []}
THUNDER_DATA = {
    "created_time": "2026-09-04T10:15:00+00:00",
    "reference_time": "2026-09-04T09:00:00+00:00",
    "current": {"valid_time": "2026-09-04T11:00:00+00:00", "probability": 25.5},
    "forecast": [{"valid_time": "2026-09-04T11:00:00+00:00", "probability": 25.5}],
    "grid_latitude": 58.0,
    "grid_longitude": 16.0,
    "data_source_url": "https://opendata-download-metfcst.smhi.se/",
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
            return_value=deepcopy(WARNING_DATA),
        ) as warnings,
        patch(
            "custom_components.smhi_alerts.fire_risk.SmhiFireRiskCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=deepcopy(FIRE_DATA),
        ) as fire,
        patch(
            "custom_components.smhi_alerts.thunder.SmhiThunderCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=deepcopy(THUNDER_DATA),
        ) as thunder,
    ):
        yield warnings, fire, thunder


async def setup_entry(hass, *, enabled=True, fire=False):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Thunder test",
        version=4,
        data={"mode": "district", "district": "12", "language": "sv"},
        options={
            CONF_THUNDER_PROBABILITY_ENABLED: enabled,
            CONF_THUNDER_PROBABILITY_LOCATION: {"latitude": 58, "longitude": 16},
            "fire_risk_enabled": fire,
            "fire_risk_location": {"latitude": 59, "longitude": 17},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass, entry, suffix="thunder_probability", domain="sensor"):
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert entity_id is not None
    return hass.states.get(entity_id)


async def test_disabled_thunder_keeps_existing_entities_and_never_fetches(
    hass, sources
):
    _, fire, thunder = sources
    entry = await setup_entry(hass, enabled=False, fire=True)
    thunder.assert_not_called()
    fire.assert_awaited_once()
    assert entry.runtime_data.thunder is None
    assert (
        len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 5
    )
    assert state(hass, entry, "forest_fire_risk").state == "high"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_percentage_sensor_preserves_forecast_semantics_and_warnings(
    hass, sources
):
    entry = await setup_entry(hass, fire=True)
    probability = state(hass, entry)
    assert probability.state == "25.5"
    assert probability.attributes["unit_of_measurement"] == "%"
    assert "state_class" not in probability.attributes
    assert "device_class" not in probability.attributes
    assert probability.attributes["source_kind"] == "local_thunder_probability_forecast"
    assert probability.attributes["valid_time"] == THUNDER_DATA["current"]["valid_time"]
    assert probability.attributes["forecast"] == THUNDER_DATA["forecast"]
    warning = state(hass, entry, "smhi_alert_sensor")
    assert (
        warning.attributes["warnings_count"] == warning.attributes["alerts_count"] == 1
    )
    assert warning.attributes["highest_severity"] == "YELLOW"
    assert state(hass, entry, "smhi_alert_active", "binary_sensor").state == "on"
    assert state(hass, entry, "forest_fire_risk").state == "high"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_initial_thunder_failure_does_not_block_other_sources_and_recovers(
    hass, sources
):
    _, _, thunder = sources
    thunder.side_effect = [UpdateFailed("Source unavailable"), deepcopy(THUNDER_DATA)]
    entry = await setup_entry(hass, fire=True)
    assert state(hass, entry).state == "unavailable"
    assert state(hass, entry, "forest_fire_risk").state == "high"
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert (
        state(hass, entry).attributes["source_kind"]
        == "local_thunder_probability_forecast"
    )
    await entry.runtime_data.thunder.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, entry).state == "25.5"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_fire_failure_does_not_block_thunder(hass, sources):
    _, fire, _ = sources
    fire.side_effect = UpdateFailed("Fire source unavailable")
    entry = await setup_entry(hass, fire=True)
    assert state(hass, entry, "forest_fire_risk").state == "unavailable"
    assert state(hass, entry).state == "25.5"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_zero_unknown_and_outage_remain_distinct_with_stable_attributes(
    hass, sources
):
    _, _, thunder = sources
    entry = await setup_entry(hass)
    keys = state(hass, entry).attributes.keys()
    for value, expected in [(0, "0"), (None, "unknown")]:
        updated = deepcopy(THUNDER_DATA)
        updated["current"]["probability"] = value
        thunder.return_value = updated
        await entry.runtime_data.thunder.async_refresh()
        await hass.async_block_till_done()
        assert state(hass, entry).state == expected
        assert state(hass, entry).attributes.keys() == keys
    thunder.side_effect = UpdateFailed("Source unavailable")
    await entry.runtime_data.thunder.async_refresh()
    await hass.async_block_till_done()
    assert state(hass, entry).state == "unavailable"
    # HA deliberately omits dynamic extra attributes while unavailable, but
    # static source identity must remain discoverable in the card editor.
    assert (
        state(hass, entry).attributes["source_kind"]
        == "local_thunder_probability_forecast"
    )
    assert state(hass, entry).attributes["probability_unit"] == "%"
    assert "forecast" not in state(hass, entry).attributes
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_toggle_location_reload_and_cleanup_preserve_entity_identity(
    hass, sources
):
    _, _, thunder = sources
    entry = await setup_entry(hass, enabled=False)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_THUNDER_PROBABILITY_ENABLED: True}
    )
    await hass.async_block_till_done()
    entity_id = state(hass, entry).entity_id
    first = entry.runtime_data.thunder
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_THUNDER_PROBABILITY_LOCATION: {"latitude": 59, "longitude": 17},
        },
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.thunder is not first
    assert state(hass, entry).entity_id == entity_id
    assert not list(first.async_contexts())
    assert first._shutdown_requested
    assert (
        len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 3
    )
    second = entry.runtime_data.thunder
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_THUNDER_PROBABILITY_ENABLED: False}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.thunder is None
    assert second._shutdown_requested
    thunder.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    thunder.assert_not_called()
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_locations_have_independent_coordinators_and_entities(hass, sources):
    first = await setup_entry(hass)
    second = await setup_entry(hass)
    assert first.runtime_data.thunder is not second.runtime_data.thunder
    assert state(hass, first).entity_id != state(hass, second).entity_id
    assert await hass.config_entries.async_unload(first.entry_id)
    assert state(hass, second).state == "25.5"
    assert await hass.config_entries.async_unload(second.entry_id)


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
def test_invalid_point_never_uses_warning_or_fire_location(location):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"latitude": 58, "longitude": 16},
        options={
            CONF_THUNDER_PROBABILITY_ENABLED: True,
            CONF_THUNDER_PROBABILITY_LOCATION: location,
            "fire_risk_location": {"latitude": 59, "longitude": 17},
        },
    )
    assert _thunder_settings(entry) == (True, None, None)
