from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.smhi_alerts import frontend
from custom_components.smhi_alerts.const import FRONTEND_DATA_KEY

CARD_PATH = Path(__file__).parents[1] / "www" / "smhi-alert-card.js"


def test_card_uses_policy_compliant_osm_tiles() -> None:
    card_text = CARD_PATH.read_text(encoding="utf-8")

    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in card_text
    assert "{s}.tile.openstreetmap.org" not in card_text
    assert "referrerPolicy: MAP_TILE_REFERRER_POLICY" in card_text
    assert "attributionControl: true" in card_text
    assert ".leaflet-control-attribution { display: none; }" not in card_text
    assert "https://www.openstreetmap.org/copyright" in card_text


def test_card_validates_custom_tile_provider_config() -> None:
    card_text = CARD_PATH.read_text(encoding="utf-8")

    assert "Custom map tile URL must include {z}, {x}, and {y}." in card_text
    assert "Custom map tile URL must use HTTPS or be same-origin." in card_text
    assert "Custom map tile attribution is required." in card_text
    assert "Map tile max zoom must be an integer between 0 and" in card_text
    assert "new URL(tileUrl, window.location.href)" in card_text


def test_card_editor_exposes_tile_provider_fields() -> None:
    card_text = CARD_PATH.read_text(encoding="utf-8")

    assert card_text.count("name: 'map_tile_url'") == 1
    assert card_text.count("name: 'map_tile_attribution'") == 1
    assert card_text.count("name: 'map_tile_max_zoom'") == 1


@pytest.mark.asyncio
async def test_frontend_refreshes_card_after_integration_reload(monkeypatch) -> None:
    hass = SimpleNamespace(data={FRONTEND_DATA_KEY: {"setup_done": True}})
    calls: list[str] = []

    async def _fake_cache_key(_hass):
        return "3.3.0-new"

    async def _fake_sync(_hass):
        calls.append("sync")

    async def _fake_ensure(_hass):
        calls.append("resource")
        return True

    monkeypatch.setattr(frontend, "_cache_key_for_dev", _fake_cache_key)
    monkeypatch.setattr(frontend, "_async_sync_assets_to_local_www", _fake_sync)
    monkeypatch.setattr(frontend, "_async_ensure_card_resource", _fake_ensure)

    await frontend.async_setup_frontend(hass)

    assert calls == ["sync", "resource"]
    assert hass.data[FRONTEND_DATA_KEY]["cache_key"] == "3.3.0-new"
