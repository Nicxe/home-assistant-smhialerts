"""Optional point sources require confirmation and preserve other choices."""

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.config_flow import _build_entry_data
from custom_components.smhi_alerts.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
SOURCES = ["wind", "precipitation", "analysis"]
POINT = {"latitude": 58, "longitude": 16}
WARNING_OPTIONS = {
    "mode": "district",
    "district": "14",
    "language": "sv",
    "include_messages": True,
    "include_geometry": False,
    "exclude_sea": True,
    "message_types": ["SNOW"],
}


@pytest.fixture(autouse=True)
def no_network_or_setup():
    with (
        patch(
            "custom_components.smhi_alerts.config_flow._async_get_district_options",
            return_value=[{"value": "14", "label": "Västra Götalands län"}],
        ),
        patch("custom_components.smhi_alerts.async_setup", return_value=True),
        patch("custom_components.smhi_alerts.async_setup_entry", return_value=True),
    ):
        yield


def test_legacy_settings_leave_all_new_sources_off_without_guessed_locations():
    result = _build_entry_data(WARNING_OPTIONS, 58, 16)
    for source in SOURCES:
        assert result[f"{source}_enabled"] is False
        assert f"{source}_location" not in result


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize(
    "location",
    [
        None,
        {},
        {"latitude": True, "longitude": 16},
        {"latitude": float("nan"), "longitude": 16},
        {"latitude": 58, "longitude": 181},
    ],
)
def test_enabled_source_rejects_invalid_point_instead_of_using_home(source, location):
    with pytest.raises(ValueError, match=f"invalid_{source}_location"):
        _build_entry_data(
            {
                **WARNING_OPTIONS,
                f"{source}_enabled": True,
                f"{source}_location": location,
            },
            58,
            16,
        )


@pytest.mark.parametrize("source", SOURCES)
async def test_options_require_independent_point_confirmation(hass, source):
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=WARNING_OPTIONS)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"]({})[f"{source}_enabled"] is False
    field = next(
        key for key in result["data_schema"].schema if key == f"{source}_location"
    )
    assert field.description["suggested_value"] == {
        "latitude": hass.config.latitude,
        "longitude": hass.config.longitude,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**WARNING_OPTIONS, f"{source}_enabled": True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {f"{source}_location": f"invalid_{source}_location"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {**WARNING_OPTIONS, f"{source}_enabled": True, f"{source}_location": POINT},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[f"{source}_location"] == POINT
    for other in SOURCES:
        assert entry.options[f"{other}_enabled"] is (other == source)


@pytest.mark.parametrize("source", SOURCES)
async def test_older_options_keep_saved_sources_and_station_without_api_calls(
    hass, source
):
    saved = {
        **WARNING_OPTIONS,
        "snow_depth_enabled": True,
        "snow_depth_station": "72620",
        "snow_depth_parameter": "8",
        **{
            key: value
            for item in SOURCES
            for key, value in [(f"{item}_enabled", True), (f"{item}_location", POINT)]
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=saved)
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.smhi_alerts.config_flow._async_get_snow_depth_stations",
            new_callable=AsyncMock,
        ) as stations,
        patch(
            "custom_components.smhi_alerts.config_flow._async_validate_snow_depth_station",
            new_callable=AsyncMock,
        ) as validate,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {**WARNING_OPTIONS, f"{source}_enabled": False}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        for other in SOURCES:
            assert entry.options[f"{other}_enabled"] is (other != source)
            assert entry.options[f"{other}_location"] == POINT
        assert entry.options["snow_depth_station"] == "72620"
        assert entry.options["snow_depth_parameter"] == "8"
        stations.assert_not_called()
        validate.assert_not_called()
