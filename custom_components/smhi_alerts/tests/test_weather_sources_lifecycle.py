"""Optional weather sources preserve entry identity and share point downloads."""

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import SpeedConverter
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smhi_alerts import (
    _analysis_settings,
    _precipitation_settings,
    _wind_settings,
)
from custom_components.smhi_alerts.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
POINT = {"latitude": 58, "longitude": 16}
SOURCE_SETTINGS = [
    ("wind", "wind", "wind_gust"),
    ("precipitation", "precipitation", "precipitation_probability"),
    ("analysis", "analysis", "analysed_precipitation"),
]


@pytest.fixture
def sources():
    now = dt_util.utcnow()
    future = (now + timedelta(hours=1)).isoformat()
    past = (now - timedelta(hours=1)).isoformat()
    data = {
        "wind": {
            "current": {"valid_time": future, "gust": 6},
            "forecast": [],
            "max_gust_24h": 10,
            "max_gust_time": future,
            "max_complete": True,
        },
        "precipitation": {
            "current": {
                "valid_time": future,
                "interval_start": now.isoformat(),
                "probability": 75,
                "amount": 1.5,
            },
            "forecast": [],
        },
        "analysis": {
            "current": {"valid_time": past, "precipitation": 0.5, "snow_change": -0.1},
            "history": [],
        },
    }
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
            "custom_components.smhi_alerts.wind.SmhiWindCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=data["wind"],
        ) as wind,
        patch(
            "custom_components.smhi_alerts.precipitation.SmhiPrecipitationCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=data["precipitation"],
        ) as precipitation,
        patch(
            "custom_components.smhi_alerts.mesan.SmhiMesanCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value=data["analysis"],
        ) as analysis,
    ):
        yield {"wind": wind, "precipitation": precipitation, "analysis": analysis}


async def setup_entry(hass, *, enabled=True, extra=None):
    options = {
        key: value
        for source, _, _ in SOURCE_SETTINGS
        for key, value in [
            (f"{source}_enabled", enabled),
            (f"{source}_location", POINT),
        ]
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Weather sources",
        version=4,
        data={"mode": "district", "district": "14", "language": "sv"},
        options={**options, **(extra or {})},
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


async def test_disabled_sources_do_not_download(hass, sources):
    entry = await setup_entry(hass, enabled=False)
    for source in sources.values():
        source.assert_not_called()
    for _, field, _ in SOURCE_SETTINGS:
        assert getattr(entry.runtime_data, field) is None
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_six_forecast_and_analysis_sensors_keep_native_units_and_semantics(
    hass, sources
):
    entry = await setup_entry(hass)
    for suffix, value, unit in [
        ("wind_gust", 6, "m/s"),
        ("wind_gust_max_24h", 10, "m/s"),
        ("precipitation_probability", 75, "%"),
        ("precipitation_amount", 1.5, "mm"),
        ("analysed_precipitation", 0.5, "mm"),
        ("analysed_snow_change", -0.1, "cm"),
    ]:
        entity = state(hass, entry, suffix)
        if unit == "m/s":
            unit = hass.config.units.get_converted_unit("wind_speed", "m/s") or "m/s"
            value = SpeedConverter.convert(value, "m/s", unit)
        assert float(entity.state) == pytest.approx(value)
        assert entity.attributes["unit_of_measurement"] == unit
        assert "state_class" not in entity.attributes
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("source,field,suffix", SOURCE_SETTINGS)
async def test_outage_of_one_source_does_not_block_warnings_or_other_sources(
    hass, sources, source, field, suffix
):
    data = deepcopy(sources[source].return_value)
    sources[source].side_effect = [UpdateFailed("Unavailable"), data]
    entry = await setup_entry(hass)
    assert state(hass, entry, suffix).state == "unavailable"
    for other, _, other_suffix in SOURCE_SETTINGS:
        if other != source:
            assert state(hass, entry, other_suffix).state not in (
                "unknown",
                "unavailable",
            )
    assert state(hass, entry, "smhi_alert_sensor").state == "Varning"
    await getattr(entry.runtime_data, field).async_refresh()
    await hass.async_block_till_done()
    assert state(hass, entry, suffix).state not in ("unknown", "unavailable")
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("source,field,suffix", SOURCE_SETTINGS)
async def test_location_toggle_and_reload_keep_ids_and_stop_old_coordinator(
    hass, sources, source, field, suffix
):
    entry = await setup_entry(hass)
    entity_id = state(hass, entry, suffix).entity_id
    old = getattr(entry.runtime_data, field)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            f"{source}_location": {"latitude": 59, "longitude": 17},
        },
    )
    await hass.async_block_till_done()
    assert old._shutdown_requested
    assert not list(old.async_contexts())
    assert state(hass, entry, suffix).entity_id == entity_id
    second = getattr(entry.runtime_data, field)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, f"{source}_enabled": False}
    )
    await hass.async_block_till_done()
    assert second._shutdown_requested
    assert getattr(entry.runtime_data, field) is None
    sources[source].reset_mock()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    sources[source].assert_not_called()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "helper,key",
    [
        (_wind_settings, "wind"),
        (_precipitation_settings, "precipitation"),
        (_analysis_settings, "analysis"),
    ],
)
@pytest.mark.parametrize(
    "point",
    [
        None,
        {},
        {"latitude": True, "longitude": 16},
        {"latitude": float("nan"), "longitude": 16},
        {"latitude": 91, "longitude": 16},
    ],
)
def test_invalid_point_does_not_fall_back_to_other_source(helper, key, point):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            f"{key}_enabled": True,
            f"{key}_location": point,
            "winter_location": POINT,
        },
    )
    assert helper(entry) == (True, None, None)


async def test_four_same_point_snow_sources_make_one_actual_superset_download(hass):
    now = dt_util.utcnow()
    payload = {
        "createdTime": now.isoformat(),
        "referenceTime": now.isoformat(),
        "geometry": {"type": "Point", "coordinates": [16, 58]},
        "timeSeries": [
            {
                "time": (now + timedelta(hours=hour)).isoformat(),
                "intervalParametersStartTime": (
                    now + timedelta(hours=hour - 1)
                ).isoformat(),
                "data": {
                    "thunderstorm_probability": 25,
                    "predominant_precipitation_type_at_surface": 5,
                    "probability_of_frozen_precipitation": 0.75,
                    "air_temperature": -1,
                    "wind_speed_of_gust": 6,
                    "probability_of_precipitation": 80,
                    "precipitation_amount_mean": 1.5,
                },
            }
            for hour in range(1, 50)
        ],
    }
    with (
        patch(
            "custom_components.smhi_alerts.async_setup_frontend", new_callable=AsyncMock
        ),
        patch(
            "custom_components.smhi_alerts.sensor.SmhiAlertCoordinator._async_update_data",
            new_callable=AsyncMock,
            return_value={"state": "Varning", "attributes": {}},
        ),
        patch(
            "custom_components.smhi_alerts.snow.SmhiSnowClient._async_get_json",
            new_callable=AsyncMock,
            return_value=payload,
        ) as download,
    ):
        entry = await setup_entry(
            hass,
            enabled=False,
            extra={
                "thunder_probability_enabled": True,
                "thunder_probability_location": POINT,
                "winter_enabled": True,
                "winter_location": POINT,
                "wind_enabled": True,
                "precipitation_enabled": True,
            },
        )
        assert download.await_count == 1
        client = entry.runtime_data.thunder._client
        assert (
            client
            is entry.runtime_data.winter._client
            is entry.runtime_data.wind._client
            is entry.runtime_data.precipitation._client
        )
        parameters = set(
            parse_qs(urlsplit(download.call_args.args[0]).query)["parameters"][0].split(
                ","
            )
        )
        assert parameters == set(payload["timeSeries"][0]["data"])
        assert float(state(hass, entry, "wind_gust").state) == pytest.approx(
            SpeedConverter.convert(
                6,
                "m/s",
                (hass.config.units.get_converted_unit("wind_speed", "m/s") or "m/s"),
            )
        )
        assert float(state(hass, entry, "precipitation_amount").state) == 1.5
        await asyncio.gather(
            *(
                coord.async_refresh()
                for coord in (
                    entry.runtime_data.thunder,
                    entry.runtime_data.winter,
                    entry.runtime_data.wind,
                    entry.runtime_data.precipitation,
                )
            )
        )
        assert download.await_count == 1
        assert await hass.config_entries.async_unload(entry.entry_id)
