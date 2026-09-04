"""Verify optional fire risk through real Home Assistant entry lifecycles."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts import _fire_risk_settings
from custom_components.smhi_alerts.const import (
    CONF_FIRE_RISK_ENABLED,
    CONF_FIRE_RISK_LOCATION,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

WARNING_DATA = {
    "state": "Varning",
    "attributes": {
        "messages": [],
        "notice": "Official warning",
        "warnings_count": 1,
        "messages_count": 0,
        "alerts_count": 1,
        "highest_severity": "YELLOW",
    },
}
FIRE_DAY = {
    "date": "2026-09-04",
    "valid_time": "2026-09-04T12:00:00+00:00",
    "forest_fire_risk": "extreme",
    "grass_fire_risk": None,
    "forest_dryness": "extremely_dry",
    "forest_fire_risk_code": 6,
    "grass_fire_risk_code": None,
    "forest_dryness_code": 6,
}
FIRE_DATA = {
    "approved_time": "2026-09-04T10:13:00+00:00",
    "reference_time": "2026-09-02T12:00:00+00:00",
    "current": FIRE_DAY,
    "forecast": [FIRE_DAY],
}


@pytest.fixture
def mocked_sources():
    """All external I/O is mocked; test only entry/entity integration here."""
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
    ):
        yield warnings, fire


async def _setup(hass, *, enabled=False):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SMHI Alerts test",
        version=4,
        data={"mode": "district", "district": "12", "language": "sv"},
        options={
            CONF_FIRE_RISK_ENABLED: enabled,
            CONF_FIRE_RISK_LOCATION: {"latitude": 58.0, "longitude": 16.0},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass, entry, suffix, domain="sensor"):
    entity_id = er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{entry.entry_id}_{suffix}"
    )
    assert entity_id is not None
    return hass.states.get(entity_id)


async def test_legacy_entry_keeps_two_entities_and_never_fetches_fire(
    hass, mocked_sources
):
    _, fire = mocked_sources
    entry = await _setup(hass)
    fire.assert_not_called()
    assert entry.runtime_data.fire_risk is None
    assert (
        len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 2
    )
    assert _state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert _state(hass, entry, "smhi_alert_active", "binary_sensor").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_fire_classes_are_separate_and_missing_class_stays_unknown(
    hass, mocked_sources
):
    entry = await _setup(hass, enabled=True)
    forest = _state(hass, entry, "forest_fire_risk")
    assert forest.state == "extreme"
    assert forest.attributes["raw_class"] == 6
    assert forest.attributes["source_kind"] == "local_fire_risk_forecast"
    assert forest.attributes["forecast"] == [FIRE_DAY]
    assert _state(hass, entry, "grass_fire_risk").state == "unknown"
    assert _state(hass, entry, "forest_dryness").state == "extremely_dry"
    warning = _state(hass, entry, "smhi_alert_sensor")
    assert warning.attributes["highest_severity"] == "YELLOW"
    assert (
        warning.attributes["warnings_count"] == warning.attributes["alerts_count"] == 1
    )
    assert "forecast" not in warning.attributes
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_initial_fire_failure_loads_warnings_and_recovers(hass, mocked_sources):
    _, fire = mocked_sources
    fire.side_effect = [UpdateFailed("Forecast unavailable"), deepcopy(FIRE_DATA)]
    entry = await _setup(hass, enabled=True)
    assert _state(hass, entry, "forest_fire_risk").state == "unavailable"
    assert _state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert _state(hass, entry, "smhi_alert_active", "binary_sensor").state == "on"
    await entry.runtime_data.fire_risk.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, entry, "forest_fire_risk").state == "extreme"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_fire_toggle_and_location_reload_preserve_unique_ids(
    hass, mocked_sources
):
    _, fire = mocked_sources
    entry = await _setup(hass)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_FIRE_RISK_ENABLED: True}
    )
    await hass.async_block_till_done()
    forest_id = _state(hass, entry, "forest_fire_risk").entity_id
    first_coordinator = entry.runtime_data.fire_risk
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_FIRE_RISK_LOCATION: {"latitude": 59.0, "longitude": 17.0},
        },
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.fire_risk is not first_coordinator
    assert _state(hass, entry, "forest_fire_risk").entity_id == forest_id
    assert (
        len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)) == 5
    )
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_FIRE_RISK_ENABLED: False}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.fire_risk is None
    assert not list(first_coordinator.async_contexts())
    fire.reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    fire.assert_not_called()
    assert _state(hass, entry, "smhi_alert_active", "binary_sensor").state == "on"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_two_entries_do_not_share_fire_coordinators(hass, mocked_sources):
    first = await _setup(hass, enabled=True)
    second = await _setup(hass, enabled=True)
    assert first.runtime_data.fire_risk is not second.runtime_data.fire_risk
    assert (
        _state(hass, first, "forest_fire_risk").entity_id
        != _state(hass, second, "forest_fire_risk").entity_id
    )
    assert await hass.config_entries.async_unload(first.entry_id)
    assert _state(hass, second, "forest_fire_risk").state == "extreme"
    assert await hass.config_entries.async_unload(second.entry_id)


@pytest.mark.parametrize(
    "location",
    [
        None,
        {},
        {"latitude": float("nan"), "longitude": 16},
        {"latitude": 91, "longitude": 16},
    ],
)
def test_invalid_fire_location_does_not_fall_back_to_warning_point(location):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"latitude": 58, "longitude": 16},
        options={CONF_FIRE_RISK_ENABLED: True, CONF_FIRE_RISK_LOCATION: location},
    )
    assert _fire_risk_settings(entry) == (True, None, None)
