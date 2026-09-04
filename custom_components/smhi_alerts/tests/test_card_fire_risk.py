"""Exercise the actual card JavaScript without browser or network dependencies."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

CARD_PATH = Path(__file__).parents[1] / "www" / "smhi-alert-card.js"

HARNESS = """
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const escape = (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
const template = (strings, ...values) => ({ strings, values });
const output = (value) => {
  if (Array.isArray(value)) return value.map(output).join('');
  if (value && value.strings) return value.strings.reduce((text, part, index) => text + part + output(value.values[index]), '');
  return value === undefined || value === null || typeof value === 'function' ? '' : escape(value);
};
const elements = new Map();
globalThis.customElements = { get: (name) => elements.get(name), define: (name, value) => elements.set(name, value) };
globalThis.window = {
  LitElement: class {}, litHtml: { html: template, css: template },
  location: { href: 'https://ha.test/', origin: 'https://ha.test' },
};
await import(pathToFileURL(process.argv[2]));
const Card = elements.get('smhi-alert-card');
const Editor = elements.get('smhi-alert-card-editor');
const card = new Card();
card.setConfig({ entity: 'sensor.alerts', fire_risk_entity: 'sensor.fire_risk' });
card._fireRiskToday = () => '2026-09-04';
const day = (date, overrides = {}) => ({
  date, valid_time: `${date}T12:00:00Z`, forest_fire_risk: 'low', forest_fire_risk_code: 2,
  grass_fire_risk: 'season_over', grass_fire_risk_code: 2, forest_dryness: 'wet', forest_dryness_code: 2, ...overrides,
});
const fire = (overrides = {}) => ({
  state: 'low', attributes: {
    source_kind: 'local_fire_risk_forecast', current: day('2026-09-04'),
    forecast: [day('2026-09-04'), day('2026-09-05')], approved_time: '2026-09-04T10:13:00Z', ...overrides,
  },
});
card.hass = { language: 'sv-SE', states: {
  'sensor.alerts': { state: 'Inga varningar', attributes: { messages: [], highest_severity: 'NONE', alerts_count: 0 } },
  'sensor.fire_risk': fire(),
}};
"""


def run_card(script: str) -> None:
    """Fail with the JavaScript assertion output, rather than a generic exit code."""
    node = shutil.which("node")
    assert node is not None, "Node.js is required for card behavior tests"
    result = subprocess.run(
        [node, "--input-type=module", "-", str(CARD_PATH)],
        input=HARNESS + script,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_optional_section_keeps_official_alerts_unchanged() -> None:
    run_card("""
const before = JSON.stringify(card._visibleMessages());
let rendered = output(card.render());
assert.ok(rendered.includes('Inga varningar'));
assert.ok(rendered.indexOf('Inga varningar') < rendered.indexOf('Lokal brandrisk'));
assert.ok(rendered.includes('Säsongen är slut'));
assert.ok(rendered.includes('Kommande dagar (1)'));
assert.equal(JSON.stringify(card._visibleMessages()), before);
assert.equal(card.hass.states['sensor.alerts'].attributes.highest_severity, 'NONE');
card.setConfig({ entity: 'sensor.alerts', show_header: false, show_empty_message: false });
assert.equal(card.getCardSize(), 0);
assert.ok(!output(card.render()).includes('Lokal brandrisk'));
card.setConfig({ entity: 'sensor.alerts', fire_risk_entity: 'sensor.fire_risk', show_header: false, show_empty_message: false });
assert.equal(card.getCardSize(), 3);
assert.ok(output(card.render()).includes('Lokal brandrisk'));
""")


@pytest.mark.parametrize("state", ["unavailable", "unexpected", "6", ""])
def test_unavailable_entity_never_shows_cached_low_risk(state: str) -> None:
    run_card(f"""
card.hass.states['sensor.fire_risk'].state = {json.dumps(state)};
assert.equal(card._fireRiskData(), null);
const rendered = output(card._renderFireRisk());
assert.ok(rendered.includes('Dagens brandrisk är inte tillgänglig'));
assert.ok(!rendered.includes('Säsongen är slut'));
assert.ok(!rendered.includes('Kommande dagar'));
""")


def test_wrong_entity_or_missing_entity_cannot_masquerade_as_fire_risk() -> None:
    run_card("""
card.hass.states['sensor.fire_risk'].attributes.source_kind = 'official_warning';
assert.equal(card._fireRiskData(), null);
delete card.hass.states['sensor.fire_risk'];
assert.equal(card._fireRiskData(), null);
assert.throws(() => card.setConfig({ entity: 'sensor.alerts', fire_risk_entity: 'binary_sensor.fire' }));
""")


def test_unknown_selected_parameter_keeps_other_parameters_available() -> None:
    run_card("""
card.hass.states['sensor.fire_risk'] = fire({ current: day('2026-09-04', {
  forest_fire_risk: 'extreme', grass_fire_risk: null, forest_dryness: 'extremely_dry',
}) });
card.hass.states['sensor.fire_risk'].state = 'unknown';
const rendered = output(card._renderFireRisk());
assert.ok(rendered.includes('5E · Extremt stor'));
assert.ok(rendered.includes('Data saknas'));
assert.ok(rendered.includes('5E · Extremt torrt'));
assert.ok(rendered.includes('Kommande dagar'));
""")


def test_sorts_real_dates_and_excludes_yesterday_and_invalid_days() -> None:
    run_card("""
card.hass.states['sensor.fire_risk'] = fire({ forecast: [
  day('2026-09-06'), day('2026-09-03', { forest_fire_risk: 'extreme' }),
  day('2026-09-04'), day('2026-09-05'), day('2026-09-05'), day('2026-02-30'), {},
] });
assert.deepEqual(card._fireRiskData().forecast.map((row) => row.date), ['2026-09-05', '2026-09-06']);
assert.equal(card._fireRiskData().current.forest_fire_risk, 'low');
card.hass.states['sensor.fire_risk'].attributes.current = day('2026-09-03');
assert.equal(card._fireRiskData().current, null);
assert.ok(output(card._renderFireRisk()).includes('Dagens brandrisk är inte tillgänglig'));
""")


def test_translates_special_classes_and_rejects_untrusted_values() -> None:
    run_card("""
assert.equal(card._fireRiskLabel('forest_fire_risk', 'extreme'), '5E · Extremt stor');
assert.equal(card._fireRiskLabel('forest_dryness', 'extremely_dry'), '5E · Extremt torrt');
assert.equal(card._fireRiskLabel('grass_fire_risk', 'very_high'), 'Mycket stor');
assert.equal(card._fireRiskLabel('grass_fire_risk', 'snow_covered'), 'Snötäckt mark');
card.hass.states['sensor.fire_risk'] = fire({ current: day('2026-09-04', {
  forest_fire_risk: '<img src=x onerror=alert(1)>', grass_fire_risk: -1, forest_dryness: 'unknown',
}) });
assert.deepEqual(card._fireRiskData().current, {
  date: '2026-09-04', forest_fire_risk: null, grass_fire_risk: null, forest_dryness: null,
});
const rendered = output(card._renderFireRisk());
assert.ok(rendered.includes('Data saknas'));
assert.ok(!rendered.includes('onerror'));
card.hass.language = 'en';
assert.equal(card._fireRiskLabel('grass_fire_risk', 'season_over'), 'Season over');
assert.equal(card._fireRiskLabel('forest_fire_risk', 'extreme'), '5E · Extreme');
""")


def test_fire_only_changes_and_language_changes_trigger_rendering() -> None:
    run_card("""
const changed = new Map([['hass', {}]]);
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.fire_risk'].attributes.current.forest_fire_risk = 'high';
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.fire_risk'].state = 'unavailable';
assert.equal(card.shouldUpdate(changed), true);
card.hass.language = 'en';
assert.equal(card.shouldUpdate(changed), true);
""")


def test_editor_exposes_optional_sensor_and_keeps_existing_values() -> None:
    run_card("""
const editor = new Editor();
editor.hass = card.hass;
editor.setConfig({ entity: 'sensor.alerts', fire_risk_entity: 'sensor.fire_risk' });
const rendered = JSON.stringify(editor.render());
assert.ok(rendered.includes('Brandrisksensor (valfri)'));
assert.ok(rendered.includes('"device_class":"enum"'));
let event;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
editor.dispatchEvent = (value) => { event = value; };
editor._valueChanged({ detail: { value: { fire_risk_entity: '' } } });
assert.equal(event.detail.config.entity, 'sensor.alerts');
assert.equal(event.detail.config.fire_risk_entity, '');
""")
