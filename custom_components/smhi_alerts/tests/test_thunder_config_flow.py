"""Keep thunderstorm forecasts, fire risk and issued warning filters independent."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.config_flow import _build_entry_data
from custom_components.smhi_alerts.const import (
    CONF_DISTRICT,
    CONF_EXCLUDE_SEA,
    CONF_FIRE_RISK_ENABLED,
    CONF_FIRE_RISK_LOCATION,
    CONF_INCLUDE_GEOMETRY,
    CONF_INCLUDE_MESSAGES,
    CONF_LANGUAGE,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_MESSAGE_TYPES,
    CONF_MODE,
    CONF_RADIUS_KM,
    CONF_THUNDER_PROBABILITY_ENABLED,
    CONF_THUNDER_PROBABILITY_LOCATION,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

FIRE_POINT = {"latitude": 58, "longitude": 16}
THUNDER_POINT = {"latitude": 57.7, "longitude": 11.97}
WARNING_OPTIONS = {
    CONF_MODE: "district",
    CONF_DISTRICT: "14",
    CONF_LANGUAGE: "sv",
    CONF_INCLUDE_MESSAGES: True,
    CONF_INCLUDE_GEOMETRY: True,
    CONF_EXCLUDE_SEA: True,
    CONF_MESSAGE_TYPES: ["FIRE", "WATER_SHORTAGE"],
}


@pytest.fixture(autouse=True)
def mock_external_setup():
    """Use the real HA flow manager without network calls or integration setup."""
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


def test_legacy_entry_retains_fire_risk_and_defaults_thunder_to_disabled():
    existing = {
        **WARNING_OPTIONS,
        CONF_FIRE_RISK_ENABLED: True,
        CONF_FIRE_RISK_LOCATION: FIRE_POINT,
    }
    data = _build_entry_data(existing, 59, 18)
    assert {key: data[key] for key in existing} == existing
    assert data[CONF_THUNDER_PROBABILITY_ENABLED] is False
    assert CONF_THUNDER_PROBABILITY_LOCATION not in data


def test_each_source_retains_its_own_location():
    warning_point = {"latitude": 60, "longitude": 18}
    data = _build_entry_data(
        {
            **WARNING_OPTIONS,
            CONF_MODE: "coordinate",
            CONF_LOCATION: warning_point,
            CONF_RADIUS_KM: 25,
            CONF_FIRE_RISK_ENABLED: True,
            CONF_FIRE_RISK_LOCATION: FIRE_POINT,
            CONF_THUNDER_PROBABILITY_ENABLED: True,
            CONF_THUNDER_PROBABILITY_LOCATION: THUNDER_POINT,
        },
        59,
        18,
    )
    assert data[CONF_LOCATION] == warning_point
    assert data[CONF_LATITUDE] == 60
    assert data[CONF_LONGITUDE] == 18
    assert data[CONF_RADIUS_KM] == 25
    assert data[CONF_FIRE_RISK_LOCATION] == FIRE_POINT
    assert data[CONF_THUNDER_PROBABILITY_LOCATION] == THUNDER_POINT
    assert CONF_DISTRICT not in data


@pytest.mark.parametrize(
    "point",
    [
        None,
        {},
        {"latitude": 57.7},
        {"latitude": float("nan"), "longitude": 12},
        {"latitude": 58, "longitude": float("inf")},
        {"latitude": 90.1, "longitude": 12},
        {"latitude": 58, "longitude": -180.1},
        {"latitude": True, "longitude": 12},
        "57.7,12",
    ],
)
def test_thunder_requires_own_valid_point_without_falling_back_to_other_sources(point):
    with pytest.raises(ValueError, match="invalid_thunder_probability_location"):
        _build_entry_data(
            {
                **WARNING_OPTIONS,
                CONF_FIRE_RISK_ENABLED: True,
                CONF_FIRE_RISK_LOCATION: FIRE_POINT,
                CONF_LOCATION: FIRE_POINT,
                CONF_THUNDER_PROBABILITY_ENABLED: True,
                CONF_THUNDER_PROBABILITY_LOCATION: point,
            },
            59,
            18,
        )


def test_valid_coordinates_do_not_use_an_approximate_sweden_boundary():
    point = {"latitude": 60, "longitude": 7}
    data = _build_entry_data(
        {
            **WARNING_OPTIONS,
            CONF_THUNDER_PROBABILITY_ENABLED: True,
            CONF_THUNDER_PROBABILITY_LOCATION: point,
        },
        59,
        18,
    )
    assert data[CONF_THUNDER_PROBABILITY_LOCATION] == point


async def test_create_flow_suggests_location_and_creates_independent_forecasts(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults[CONF_THUNDER_PROBABILITY_ENABLED] is False
    assert CONF_THUNDER_PROBABILITY_LOCATION not in defaults
    point_field = next(
        key
        for key in result["data_schema"].schema
        if key == CONF_THUNDER_PROBABILITY_LOCATION
    )
    assert point_field.description["suggested_value"] == {
        "latitude": hass.config.latitude,
        "longitude": hass.config.longitude,
    }
    submitted = {
        **WARNING_OPTIONS,
        CONF_FIRE_RISK_ENABLED: True,
        CONF_FIRE_RISK_LOCATION: FIRE_POINT,
        CONF_THUNDER_PROBABILITY_ENABLED: True,
        CONF_THUNDER_PROBABILITY_LOCATION: THUNDER_POINT,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], submitted
    )
    assert result["step_id"] == "reload_notice"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == submitted
    await hass.async_block_till_done()


async def test_create_flow_requires_confirmation_for_each_enabled_source(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: True,
            CONF_THUNDER_PROBABILITY_ENABLED: True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        CONF_FIRE_RISK_LOCATION: "invalid_fire_risk_location",
        CONF_THUNDER_PROBABILITY_LOCATION: "invalid_thunder_probability_location",
    }
    thunder_field = next(
        key
        for key in result["data_schema"].schema
        if key == CONF_THUNDER_PROBABILITY_ENABLED
    )
    assert thunder_field.description["suggested_value"] is True


@pytest.mark.parametrize("fire_enabled", [False, True])
@pytest.mark.parametrize("thunder_enabled", [False, True])
async def test_options_toggle_thunder_preserves_fire_and_warning_choices(
    hass, fire_enabled, thunder_enabled
):
    existing = {
        **WARNING_OPTIONS,
        CONF_FIRE_RISK_ENABLED: fire_enabled,
        CONF_FIRE_RISK_LOCATION: FIRE_POINT,
        CONF_THUNDER_PROBABILITY_ENABLED: not thunder_enabled,
        CONF_THUNDER_PROBABILITY_LOCATION: THUNDER_POINT,
    }
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=existing)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **WARNING_OPTIONS,
            CONF_THUNDER_PROBABILITY_ENABLED: thunder_enabled,
            CONF_THUNDER_PROBABILITY_LOCATION: THUNDER_POINT,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        **existing,
        CONF_THUNDER_PROBABILITY_ENABLED: thunder_enabled,
    }


async def test_options_require_point_when_enabling_for_the_first_time(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        data={
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: True,
            CONF_FIRE_RISK_LOCATION: FIRE_POINT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**WARNING_OPTIONS, CONF_THUNDER_PROBABILITY_ENABLED: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {
        CONF_THUNDER_PROBABILITY_LOCATION: "invalid_thunder_probability_location"
    }
    assert not entry.options


@pytest.mark.parametrize("updates", [{}, {CONF_THUNDER_PROBABILITY_ENABLED: False}])
async def test_older_options_or_disabling_thunder_keeps_both_saved_points(
    hass, updates
):
    current = {
        CONF_FIRE_RISK_ENABLED: True,
        CONF_FIRE_RISK_LOCATION: FIRE_POINT,
        CONF_THUNDER_PROBABILITY_ENABLED: True,
        CONF_THUNDER_PROBABILITY_LOCATION: THUNDER_POINT,
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=4, data=WARNING_OPTIONS, options=current
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**WARNING_OPTIONS, **updates}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**WARNING_OPTIONS, **current, **updates}


async def test_reconfigure_can_change_thunder_point_without_changing_fire_or_warnings(
    hass,
):
    existing = {
        **WARNING_OPTIONS,
        CONF_FIRE_RISK_ENABLED: True,
        CONF_FIRE_RISK_LOCATION: FIRE_POINT,
        CONF_THUNDER_PROBABILITY_ENABLED: True,
        CONF_THUNDER_PROBABILITY_LOCATION: THUNDER_POINT,
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
    new_point = {"latitude": 59, "longitude": 19}
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**WARNING_OPTIONS, CONF_THUNDER_PROBABILITY_LOCATION: new_point},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigured_successful"
    assert entry.data == {**existing, CONF_THUNDER_PROBABILITY_LOCATION: new_point}
    assert entry.options == entry.data


def test_thunder_translations_preserve_fire_and_canonical_english():
    base = Path(__file__).parents[1]
    english = json.loads((base / "translations/en.json").read_text())
    swedish = json.loads((base / "translations/sv.json").read_text())
    assert json.loads((base / "strings.json").read_text()) == english
    for translation in (english, swedish):
        assert translation["entity"]["sensor"]["thunder_probability"]["name"]
        assert len(translation["entity"]["sensor"]["forest_fire_risk"]["state"]) == 6
        for section, step in [
            ("config", "user"),
            ("config", "reconfigure"),
            ("options", "init"),
        ]:
            form = translation[section]["step"][step]
            assert CONF_THUNDER_PROBABILITY_ENABLED in form["data"]
            assert CONF_THUNDER_PROBABILITY_LOCATION in form["data_description"]
            assert "48" in form["data_description"][CONF_THUNDER_PROBABILITY_ENABLED]
            assert (
                "invalid_thunder_probability_location" in translation[section]["error"]
            )
