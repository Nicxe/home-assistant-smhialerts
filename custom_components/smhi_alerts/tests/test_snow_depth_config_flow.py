"""Snow observations require an explicit, live-checked station/source choice."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers.update_coordinator import UpdateFailed
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts.config_flow import _build_entry_data
from custom_components.smhi_alerts.const import (
    CONF_SNOW_DEPTH_CHANGE_STATION,
    CONF_SNOW_DEPTH_ENABLED,
    CONF_SNOW_DEPTH_PARAMETER,
    CONF_SNOW_DEPTH_STATION,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE_DATA = {
    "wind_enabled": False,
    "precipitation_enabled": False,
    "analysis_enabled": False,
    "mode": "district",
    "district": "14",
    "language": "sv",
    "include_messages": False,
    "include_geometry": False,
    "exclude_sea": False,
    "message_types": ["SNOW"],
    "fire_risk_enabled": False,
    "thunder_probability_enabled": False,
    "winter_enabled": False,
}
SAVED_SELECTION = {
    CONF_SNOW_DEPTH_ENABLED: True,
    CONF_SNOW_DEPTH_STATION: "72620",
    CONF_SNOW_DEPTH_PARAMETER: "8",
}
STATIONS = [
    {
        "station_id": "72620",
        "station_name": "Askim D",
        "parameter": "8",
        "distance_km": 12.34,
        "cadence": "daily",
        "parameter_summary": "momentanvärde, 1 gång/dygn, kl 06",
    },
    {
        "station_id": "72620",
        "station_name": "Askim D",
        "parameter": "52",
        "distance_km": 12.34,
        "cadence": "minute",
        "parameter_summary": "momentanvärde varje minut",
    },
    {
        "station_id": "72560",
        "station_name": "Alingsås D",
        "parameter": "8",
        "distance_km": 45,
        "cadence": "daily",
        "parameter_summary": "momentanvärde, 1 gång/dygn, kl 06",
    },
]


@pytest.fixture
def mock_sources():
    with (
        patch(
            "custom_components.smhi_alerts.config_flow._async_get_district_options",
            return_value=[
                {"value": "14", "label": "Västra Götalands län"},
                {"value": "all", "label": "Alla"},
            ],
        ),
        patch("custom_components.smhi_alerts.async_setup", return_value=True),
        patch("custom_components.smhi_alerts.async_setup_entry", return_value=True),
        patch(
            "custom_components.smhi_alerts.config_flow._async_get_snow_depth_stations",
            return_value=deepcopy(STATIONS),
        ) as discover,
        patch(
            "custom_components.smhi_alerts.config_flow._async_validate_snow_depth_station",
            return_value=None,
        ) as validate,
    ):
        yield discover, validate


async def start_options(hass, data=None):
    entry = MockConfigEntry(domain=DOMAIN, version=4, data=data or BASE_DATA)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return entry, result


def test_disabled_data_preserves_saved_station_without_ui_helper():
    assert _build_entry_data(
        {
            **BASE_DATA,
            **SAVED_SELECTION,
            CONF_SNOW_DEPTH_ENABLED: False,
            CONF_SNOW_DEPTH_CHANGE_STATION: True,
        },
        59,
        18,
    ) == {**BASE_DATA, **SAVED_SELECTION, CONF_SNOW_DEPTH_ENABLED: False}


async def test_disabled_source_has_no_discovery_or_probe(hass, mock_sources):
    entry, result = await start_options(hass)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], BASE_DATA
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SNOW_DEPTH_ENABLED] is False
    for request in mock_sources:
        request.assert_not_called()


async def test_setup_enabling_requires_explicit_station_then_reload_notice(
    hass, mock_sources
):
    discover, validate = mock_sources
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_DATA, CONF_SNOW_DEPTH_ENABLED: True}
    )
    assert result["step_id"] == "snow_depth"
    assert result["type"] is FlowResultType.FORM
    field = next(iter(result["data_schema"].schema))
    assert not field.description
    selector = result["data_schema"].schema[field]
    options = selector.config["options"]
    assert options[0]["value"] == "8:72620"
    assert "Askim D" in options[0]["label"]
    assert "12.3 km" in options[0]["label"]
    assert STATIONS[0]["parameter_summary"] in options[0]["label"]
    discover.assert_awaited_once()
    validate.assert_not_called()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SNOW_DEPTH_STATION: "52:72620"}
    )
    validate.assert_awaited_once_with(hass, "72620", "52")
    assert result["step_id"] == "reload_notice"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **BASE_DATA,
        **SAVED_SELECTION,
        CONF_SNOW_DEPTH_PARAMETER: "52",
    }
    await hass.async_block_till_done()


@pytest.mark.parametrize("bad", ["8:unknown", "72620", "52:99999", None])
async def test_unlisted_station_cannot_be_saved(hass, mock_sources, bad):
    entry, result = await start_options(hass)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_DATA, CONF_SNOW_DEPTH_ENABLED: True}
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SNOW_DEPTH_STATION: bad}
        )
    assert not entry.options
    mock_sources[1].assert_not_called()


async def test_selected_source_requires_recent_data_before_save(hass, mock_sources):
    discover, validate = mock_sources
    validate.side_effect = [UpdateFailed("No recent observation"), None]
    entry, result = await start_options(hass)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_DATA, CONF_SNOW_DEPTH_ENABLED: True}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SNOW_DEPTH_STATION: "52:72620"}
    )
    assert result["errors"] == {
        CONF_SNOW_DEPTH_STATION: "snow_depth_station_unavailable"
    }
    assert not entry.options
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SNOW_DEPTH_STATION: "8:72620"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**BASE_DATA, **SAVED_SELECTION}
    assert validate.await_args_list[1].args == (hass, "72620", "8")
    discover.assert_awaited_once()


@pytest.mark.parametrize(
    "updates", [{}, {CONF_SNOW_DEPTH_ENABLED: True}, {CONF_SNOW_DEPTH_ENABLED: False}]
)
async def test_unchanged_older_or_disabling_options_preserve_station_without_fetch(
    hass, mock_sources, updates
):
    entry, result = await start_options(hass, {**BASE_DATA, **SAVED_SELECTION})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_DATA, **updates}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**BASE_DATA, **SAVED_SELECTION, **updates}
    for request in mock_sources:
        request.assert_not_called()


async def test_explicit_change_is_suggested_but_never_automatic(hass, mock_sources):
    entry, result = await start_options(hass, {**BASE_DATA, **SAVED_SELECTION})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            **BASE_DATA,
            CONF_SNOW_DEPTH_ENABLED: True,
            CONF_SNOW_DEPTH_CHANGE_STATION: True,
        },
    )
    assert result["step_id"] == "snow_depth"
    field = next(iter(result["data_schema"].schema))
    assert field.description["suggested_value"] == "8:72620"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SNOW_DEPTH_STATION: "8:72560"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        **BASE_DATA,
        **SAVED_SELECTION,
        CONF_SNOW_DEPTH_STATION: "72560",
    }
    assert CONF_SNOW_DEPTH_CHANGE_STATION not in entry.options


async def test_reenable_requires_confirmation_of_saved_source(hass, mock_sources):
    entry, result = await start_options(
        hass, {**BASE_DATA, **SAVED_SELECTION, CONF_SNOW_DEPTH_ENABLED: False}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_DATA, CONF_SNOW_DEPTH_ENABLED: True}
    )
    assert result["step_id"] == "snow_depth"
    assert entry.options == {}
    mock_sources[1].assert_not_called()


@pytest.mark.parametrize("failure", [UpdateFailed("Offline"), []])
async def test_discovery_failure_is_actionable_and_retry_preserves_pending_settings(
    hass, mock_sources, failure
):
    discover, validate = mock_sources
    discover.side_effect = (
        [failure, deepcopy(STATIONS)]
        if isinstance(failure, Exception)
        else [[], deepcopy(STATIONS)]
    )
    entry, result = await start_options(hass)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**BASE_DATA, CONF_SNOW_DEPTH_ENABLED: True}
    )
    assert result["errors"] == {
        "base": "cannot_connect_snow_depth"
        if isinstance(failure, Exception)
        else "no_snow_depth_stations"
    }
    assert not entry.options
    validate.assert_not_called()
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "snow_depth"
    assert not result["errors"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SNOW_DEPTH_STATION: "8:72620"}
    )
    assert entry.options == {**BASE_DATA, **SAVED_SELECTION}


async def test_reconfigure_keeps_warning_selection_and_replaces_only_station(
    hass, mock_sources
):
    entry = MockConfigEntry(
        domain=DOMAIN, version=4, data={**BASE_DATA, **SAVED_SELECTION}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_DATA, CONF_SNOW_DEPTH_CHANGE_STATION: True}
    )
    assert result["step_id"] == "snow_depth"
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SNOW_DEPTH_STATION: "8:72560"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigured_successful"
    assert (
        entry.data
        == entry.options
        == {**BASE_DATA, **SAVED_SELECTION, CONF_SNOW_DEPTH_STATION: "72560"}
    )


def test_snow_depth_translations_cover_selection_errors_and_canonical_english():
    import json
    from pathlib import Path

    base = Path(__file__).parents[1]
    english = json.loads((base / "translations/en.json").read_text())
    assert english == json.loads((base / "strings.json").read_text())
    for translation in (
        english,
        json.loads((base / "translations/sv.json").read_text()),
    ):
        assert translation["entity"]["sensor"]["snow_depth"]["name"]
        for section in ("config", "options"):
            station_form = translation[section]["step"]["snow_depth"]
            assert station_form["data"][CONF_SNOW_DEPTH_STATION]
            for error in (
                "cannot_connect_snow_depth",
                "no_snow_depth_stations",
                "invalid_snow_depth_station",
                "snow_depth_station_unavailable",
            ):
                assert translation[section]["error"][error]
        for section, step in (
            ("config", "user"),
            ("config", "reconfigure"),
            ("options", "init"),
        ):
            form = translation[section]["step"][step]
            assert form["data"][CONF_SNOW_DEPTH_ENABLED]
            assert form["data"][CONF_SNOW_DEPTH_CHANGE_STATION]
