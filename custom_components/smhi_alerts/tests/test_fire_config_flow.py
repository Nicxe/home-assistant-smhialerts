"""Fire risk options remain independent of existing warning filters."""

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
    CONF_LOCATION,
    CONF_MESSAGE_TYPES,
    CONF_MODE,
    CONF_RADIUS_KM,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

POINT = {"latitude": 57.7, "longitude": 11.97}
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
    """Exercise Home Assistant flow handling without external requests or reloads."""
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


def test_legacy_warning_options_keep_fire_risk_disabled():
    data = _build_entry_data(WARNING_OPTIONS, 59, 18)
    assert data[CONF_FIRE_RISK_ENABLED] is False
    assert CONF_FIRE_RISK_LOCATION not in data
    assert {key: data[key] for key in WARNING_OPTIONS} == WARNING_OPTIONS


def test_district_does_not_discard_fire_risk_point():
    data = _build_entry_data(
        {
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: True,
            CONF_FIRE_RISK_LOCATION: POINT,
        },
        59,
        18,
    )
    assert data[CONF_FIRE_RISK_LOCATION] == POINT
    assert data[CONF_DISTRICT] == "14"
    assert CONF_LOCATION not in data
    assert CONF_RADIUS_KM not in data


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
def test_enabled_fire_risk_requires_valid_separate_point(point):
    with pytest.raises(ValueError, match="invalid_fire_risk_location"):
        _build_entry_data(
            {
                **WARNING_OPTIONS,
                CONF_FIRE_RISK_ENABLED: True,
                CONF_FIRE_RISK_LOCATION: point,
                CONF_LOCATION: POINT,
            },
            59,
            18,
        )


def test_no_approximate_sweden_bounding_box_is_used():
    data = _build_entry_data(
        {
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: True,
            CONF_FIRE_RISK_LOCATION: {"latitude": 70, "longitude": 32},
        },
        59,
        18,
    )
    assert data[CONF_FIRE_RISK_LOCATION] == {"latitude": 70, "longitude": 32}


async def test_create_flow_shows_separate_point_and_preserves_warning_filter(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    defaults = result["data_schema"]({})
    assert defaults[CONF_FIRE_RISK_ENABLED] is False
    point_field = next(
        key for key in result["data_schema"].schema if key == CONF_FIRE_RISK_LOCATION
    )
    assert point_field.description["suggested_value"] == {
        "latitude": hass.config.latitude,
        "longitude": hass.config.longitude,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: True,
            CONF_FIRE_RISK_LOCATION: POINT,
        },
    )
    assert result["step_id"] == "reload_notice"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_FIRE_RISK_LOCATION] == POINT
    assert {key: result["data"][key] for key in WARNING_OPTIONS} == WARNING_OPTIONS
    await hass.async_block_till_done()


async def test_create_flow_invalid_location_returns_translated_field_error(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**WARNING_OPTIONS, CONF_FIRE_RISK_ENABLED: True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {CONF_FIRE_RISK_LOCATION: "invalid_fire_risk_location"}
    enabled_field = next(
        key for key in result["data_schema"].schema if key == CONF_FIRE_RISK_ENABLED
    )
    assert enabled_field.description["suggested_value"] is True


@pytest.mark.parametrize("enabled", [True, False])
async def test_options_flow_toggles_fire_risk_without_changing_warning_options(
    hass, enabled
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        data={
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: not enabled,
            CONF_FIRE_RISK_LOCATION: POINT,
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **WARNING_OPTIONS,
            CONF_FIRE_RISK_ENABLED: enabled,
            CONF_FIRE_RISK_LOCATION: POINT,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FIRE_RISK_ENABLED] is enabled
    assert entry.options[CONF_FIRE_RISK_LOCATION] == POINT
    assert {key: entry.options[key] for key in WARNING_OPTIONS} == WARNING_OPTIONS


@pytest.mark.parametrize("fire_changes", [{}, {CONF_FIRE_RISK_ENABLED: False}])
async def test_older_options_or_disabling_preserves_existing_fire_point(
    hass, fire_changes
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        data=WARNING_OPTIONS,
        options={CONF_FIRE_RISK_ENABLED: True, CONF_FIRE_RISK_LOCATION: POINT},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**WARNING_OPTIONS, **fire_changes}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_FIRE_RISK_ENABLED] is fire_changes.get(
        CONF_FIRE_RISK_ENABLED, True
    )
    assert entry.options[CONF_FIRE_RISK_LOCATION] == POINT


async def test_reconfigure_updates_fire_point_and_keeps_warning_selection(hass):
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=WARNING_OPTIONS)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["step_id"] == "reconfigure"
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **WARNING_OPTIONS,
                CONF_FIRE_RISK_ENABLED: True,
                CONF_FIRE_RISK_LOCATION: POINT,
            },
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigured_successful"
    assert entry.data[CONF_FIRE_RISK_LOCATION] == POINT
    assert entry.options[CONF_FIRE_RISK_ENABLED] is True
    assert {key: entry.options[key] for key in WARNING_OPTIONS} == WARNING_OPTIONS


def test_translations_cover_every_fire_class_and_canonical_english():
    base = Path(__file__).parents[1]
    english = json.loads((base / "translations/en.json").read_text())
    swedish = json.loads((base / "translations/sv.json").read_text())
    assert json.loads((base / "strings.json").read_text()) == english
    for translation in (english, swedish):
        assert translation["entity"]["sensor"]["forest_fire_risk"]["state"][
            "extreme"
        ].endswith("(5E)")
        assert len(translation["entity"]["sensor"]["grass_fire_risk"]["state"]) == 6
        assert len(translation["entity"]["sensor"]["forest_dryness"]["state"]) == 6
        for section, step in [
            ("config", "user"),
            ("config", "reconfigure"),
            ("options", "init"),
        ]:
            form = translation[section]["step"][step]
            assert CONF_FIRE_RISK_ENABLED in form["data"]
            assert CONF_FIRE_RISK_LOCATION in form["data_description"]
            assert "invalid_fire_risk_location" in translation[section]["error"]
