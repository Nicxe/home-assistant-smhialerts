"""Winter options use their own confirmed point without changing other sources."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.config_flow import _build_entry_data
from custom_components.smhi_alerts.const import (
    CONF_FIRE_RISK_ENABLED,
    CONF_FIRE_RISK_LOCATION,
    CONF_SNOW_DEPTH_ENABLED,
    CONF_THUNDER_PROBABILITY_ENABLED,
    CONF_THUNDER_PROBABILITY_LOCATION,
    CONF_WINTER_ENABLED,
    CONF_WINTER_LOCATION,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

WARNING_OPTIONS = {
    "wind_enabled": False,
    "precipitation_enabled": False,
    "analysis_enabled": False,
    "mode": "district",
    "district": "14",
    "language": "sv",
    "include_messages": True,
    "include_geometry": True,
    "exclude_sea": True,
    "message_types": ["SNOW", "WATER_SHORTAGE"],
}
WINTER_POINT = {"latitude": 57.7, "longitude": 11.97}
OTHER_SOURCES = {
    CONF_FIRE_RISK_ENABLED: True,
    CONF_FIRE_RISK_LOCATION: {"latitude": 58, "longitude": 16},
    CONF_THUNDER_PROBABILITY_ENABLED: True,
    CONF_THUNDER_PROBABILITY_LOCATION: {"latitude": 59, "longitude": 17},
}


@pytest.fixture(autouse=True)
def mock_external_setup():
    """Exercise real flow management while keeping setup and requests mocked."""
    with (
        patch(
            "custom_components.smhi_alerts.config_flow._async_get_district_options",
            return_value=[
                {"value": "14", "label": "Västra Götalands län"},
                {"value": "all", "label": "Alla distrikt"},
            ],
        ),
        patch("custom_components.smhi_alerts.async_setup", return_value=True),
        patch("custom_components.smhi_alerts.async_setup_entry", return_value=True),
    ):
        yield


def test_legacy_data_keeps_winter_disabled_without_assuming_a_point():
    existing = {**WARNING_OPTIONS, **OTHER_SOURCES}
    data = _build_entry_data(existing, 60, 18)
    assert data == {
        **existing,
        CONF_WINTER_ENABLED: False,
        CONF_SNOW_DEPTH_ENABLED: False,
    }
    assert CONF_WINTER_LOCATION not in data


@pytest.mark.parametrize(
    "point",
    [
        None,
        {},
        {"latitude": 57.7},
        {"latitude": float("nan"), "longitude": 12},
        {"latitude": 58, "longitude": float("inf")},
        {"latitude": -90.1, "longitude": 12},
        {"latitude": 58, "longitude": 180.1},
        {"latitude": True, "longitude": 12},
        "57.7,12",
    ],
)
def test_enabled_winter_requires_its_own_valid_location(point):
    with pytest.raises(ValueError, match="invalid_winter_location"):
        _build_entry_data(
            {
                **WARNING_OPTIONS,
                **OTHER_SOURCES,
                CONF_WINTER_ENABLED: True,
                CONF_WINTER_LOCATION: point,
            },
            60,
            18,
        )


async def test_initial_flow_suggests_home_and_requires_winter_point_confirmation(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["data_schema"]({})[CONF_WINTER_ENABLED] is False
    field = next(
        key for key in result["data_schema"].schema if key == CONF_WINTER_LOCATION
    )
    assert field.description["suggested_value"] == {
        "latitude": hass.config.latitude,
        "longitude": hass.config.longitude,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**WARNING_OPTIONS, **OTHER_SOURCES, CONF_WINTER_ENABLED: True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_WINTER_LOCATION: "invalid_winter_location"}
    submitted = {
        **WARNING_OPTIONS,
        **OTHER_SOURCES,
        CONF_WINTER_ENABLED: True,
        CONF_WINTER_LOCATION: WINTER_POINT,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], submitted
    )
    assert result["step_id"] == "reload_notice"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**submitted, CONF_SNOW_DEPTH_ENABLED: False}
    await hass.async_block_till_done()


@pytest.mark.parametrize("enabled", [False, True])
async def test_options_toggle_winter_without_changing_saved_sources(hass, enabled):
    existing = {
        **WARNING_OPTIONS,
        **OTHER_SOURCES,
        CONF_WINTER_ENABLED: not enabled,
        CONF_WINTER_LOCATION: WINTER_POINT,
    }
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=existing)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**WARNING_OPTIONS, CONF_WINTER_ENABLED: enabled}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        **existing,
        CONF_WINTER_ENABLED: enabled,
        CONF_SNOW_DEPTH_ENABLED: False,
    }


async def test_older_options_submission_preserves_enabled_winter_and_saved_point(hass):
    current = {
        **OTHER_SOURCES,
        CONF_WINTER_ENABLED: True,
        CONF_WINTER_LOCATION: WINTER_POINT,
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=4, data=WARNING_OPTIONS, options=current
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], WARNING_OPTIONS
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        **WARNING_OPTIONS,
        **current,
        CONF_SNOW_DEPTH_ENABLED: False,
    }


async def test_options_cannot_enable_winter_without_own_location(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, version=4, data={**WARNING_OPTIONS, **OTHER_SOURCES}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**WARNING_OPTIONS, CONF_WINTER_ENABLED: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_WINTER_LOCATION: "invalid_winter_location"}
    assert not entry.options


async def test_reconfigure_changes_winter_point_and_preserves_other_settings(hass):
    existing = {
        **WARNING_OPTIONS,
        **OTHER_SOURCES,
        CONF_WINTER_ENABLED: True,
        CONF_WINTER_LOCATION: WINTER_POINT,
    }
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=existing)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    new_point = {"latitude": 60, "longitude": 7}
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**WARNING_OPTIONS, CONF_WINTER_LOCATION: new_point}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigured_successful"
    assert (
        entry.data
        == entry.options
        == {**existing, CONF_WINTER_LOCATION: new_point, CONF_SNOW_DEPTH_ENABLED: False}
    )


def test_translations_cover_every_winter_type_and_canonical_english():
    base = Path(__file__).parents[1]
    english = json.loads((base / "translations/en.json").read_text())
    assert english == json.loads((base / "strings.json").read_text())
    enum_states = {
        "none",
        "rain",
        "thunderstorm",
        "freezing_rain",
        "mixed_ice",
        "snow",
        "wet_snow",
        "rain_snow",
        "ice_pellets",
        "graupel",
        "hail",
        "drizzle",
        "freezing_drizzle",
    }
    for language in (english, json.loads((base / "translations/sv.json").read_text())):
        sensors = language["entity"]["sensor"]
        assert set(sensors["winter_precipitation_type"]["state"]) == enum_states
        assert sensors["winter_frozen_probability"]["name"]
        assert sensors["winter_temperature"]["name"]
        for section, step in [
            ("config", "user"),
            ("config", "reconfigure"),
            ("options", "init"),
        ]:
            form = language[section]["step"][step]
            assert CONF_WINTER_ENABLED in form["data"]
            assert CONF_WINTER_LOCATION in form["data_description"]
            assert "48" in form["data_description"][CONF_WINTER_ENABLED]
            assert "invalid_winter_location" in language[section]["error"]
