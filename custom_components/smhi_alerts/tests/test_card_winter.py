"""Exercise the shipped winter card with the winter sensor contract."""

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
const Card = elements.get('smhi-winter-card');
const Editor = elements.get('smhi-winter-card-editor');
const card = new Card();
card.setConfig({ entity: 'sensor.winter' });
card._winterNow = () => Date.parse('2026-10-22T10:30:00Z');
const point = (time, type = 'none', probability = 0, temperature = 0) => ({
  valid_time: time, precipitation_type: type, frozen_probability: probability, temperature,
});
const winter = (state = 'none', overrides = {}) => ({ state, attributes: {
  source_kind: 'local_winter_forecast',
  created_time: '2026-10-22T10:00:00Z', reference_time: '2026-10-22T09:45:00Z',
  current: point('2026-10-22T11:00:00Z'),
  forecast: [point('2026-10-22T11:00:00Z'), point('2026-10-22T12:00:00Z', 'snow', 75.5, -1.2)],
  ...overrides,
}});
card.hass = { language: 'sv-SE', states: { 'sensor.winter': winter() } };
"""


def run_card(script: str) -> None:
    """Run against the bundled card, as CI has no HAdev development copy."""
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


def test_standalone_card_preserves_zero_and_exact_forecast_time() -> None:
    run_card("""
const data = card._winterData();
assert.equal(data.current.precipitation_type, 'none');
assert.equal(data.current.frozen_probability, 0);
assert.equal(data.current.temperature, 0);
const rendered = output(card.render());
assert.ok(rendered.includes('Vinterväder'));
assert.ok(rendered.includes('Ingen nederbörd'));
assert.ok(rendered.includes('0 %'));
assert.ok(rendered.includes('0 °C'));
assert.ok(rendered.includes('Sannolikhet för frusen nederbörd'));
assert.ok(rendered.includes('datetime=2026-10-22T11:00:00.000Z'));
assert.ok(rendered.includes('75,5 %'));
assert.ok(rendered.includes('−1,2 °C'));
assert.ok(!rendered.includes('snödjup'));
assert.ok(!rendered.includes('halkrisk'));
""")


@pytest.mark.parametrize("state", ["none", "0", "-1.2", "unknown"])
def test_any_winter_sensor_shows_known_sibling_values(state: str) -> None:
    run_card(f"""
card.hass.states['sensor.winter'] = winter({json.dumps(state)}, {{
  current: point('2026-10-22T11:00:00Z', null, 50, -1),
}});
const rendered = output(card.render());
assert.ok(rendered.includes('Data saknas'));
assert.ok(rendered.includes('50 %'));
assert.ok(rendered.includes('−1 °C'));
assert.equal(card._winterData().current.precipitation_type, null);
""")


def test_unknown_nearest_forecast_is_retained_without_substitution() -> None:
    run_card("""
card.hass.states['sensor.winter'] = winter('unknown', {
  current: point('2026-10-22T11:00:00Z', null, null, null),
  forecast: [point('2026-10-22T11:00:00Z', null, null, null), point('2026-10-22T12:00:00Z', 'snow', 75, -1)],
});
assert.equal(card._winterData().current.valid_time, '2026-10-22T11:00:00.000Z');
assert.equal(card._winterData().current.frozen_probability, null);
assert.ok(output(card.render()).includes('Data saknas'));
assert.ok(output(card.render()).includes('75 %'));
""")


def test_unavailable_or_wrong_source_never_displays_cached_forecasts() -> None:
    run_card("""
for (const state of ['unavailable', '']) {
  card.hass.states['sensor.winter'] = winter(state);
  assert.equal(card._winterData(), null);
  assert.ok(output(card.render()).includes('Vinterväder är inte tillgängligt'));
  assert.ok(!output(card.render()).includes('75,5 %'));
}
card.hass.states['sensor.winter'] = winter('none', { source_kind: 'local_thunder_probability_forecast' });
assert.equal(card._winterData(), null);
delete card.hass.states['sensor.winter'];
assert.equal(card._winterData(), null);
""")


def test_forecast_keeps_actual_times_and_excludes_past_and_outside_window() -> None:
    run_card("""
card.hass.states['sensor.winter'] = winter('none', { forecast: [
  point('2026-10-22T13:00:00Z', 'snow'), point('2026-10-22T10:30:00Z'),
  point('2026-10-22T10:00:00Z'), point('2026-10-22T11:00:00Z'),
  point('2026-10-22T13:00:00+02:00'), point('2026-10-22'), point('invalid'), {},
  point('2026-10-24T10:30:00Z'), point('2026-10-24T11:00:00Z'),
] });
assert.deepEqual(card._winterData().forecast.map((row) => row.valid_time), [
  '2026-10-22T11:00:00.000Z', '2026-10-22T13:00:00.000Z', '2026-10-24T10:30:00.000Z',
]);
card._winterNow = () => Date.parse('2026-10-22T11:00:00Z');
assert.equal(card._winterData().current, null);
assert.ok(output(card.render()).includes('Vinterväder är inte tillgängligt'));
""")


def test_validation_and_translation_never_render_untrusted_forecast_values() -> None:
    run_card("""
const bad = '<img onerror=alert(1)>';
for (const value of [true, false, '', '1', [], {}, -9, 9999, NaN, Infinity, bad]) {
  assert.equal(card._winterNumber(value, 0, 100), null);
}
assert.equal(card._winterNumber(0, 0, 100), 0);
assert.equal(card._winterNumber(100, 0, 100), 100);
card.hass.states['sensor.winter'] = winter('unknown', {
  current: point('2026-10-22T11:00:00Z', bad, 9999, 9999), forecast: [],
});
const rendered = output(card.render());
assert.ok(rendered.includes('Data saknas'));
assert.ok(!rendered.includes('onerror'));
assert.ok(!rendered.includes('9999'));
card.hass.language = 'en';
assert.equal(card._winterTypeLabel('freezing_rain'), 'Freezing rain');
assert.equal(card._winterTypeLabel('freezing_drizzle'), 'Freezing drizzle');
assert.equal(card._winterTypeLabel('wet_snow'), 'Wet snow');
assert.equal(card._winterTypeLabel('bad'), 'No data');
assert.equal(card._winterValue(12.5, '%'), '12.5 %');
card.hass.language = 'sv';
assert.equal(card._winterTypeLabel('freezing_rain'), 'Underkylt regn');
assert.equal(card._winterTypeLabel('freezing_drizzle'), 'Underkylt duggregn');
assert.equal(card._winterTypeLabel('wet_snow'), 'Blötsnö');
""")


def test_temperature_follows_ha_units_and_updates_without_new_data() -> None:
    run_card("""
assert.equal(card._winterTemperature(0), '0 °C');
const changed = new Map([['hass', {}]]);
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.config = { unit_system: { temperature: '°F' } };
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card._winterTemperature(0), '32 °F');
assert.equal(card._winterTemperature(-10), '14 °F');
assert.equal(card._winterTemperature(null), 'Data saknas');
card.hass.states['sensor.winter'].attributes.forecast[1].temperature = -2;
assert.equal(card.shouldUpdate(changed), true);
card._winterNow = () => Date.parse('2026-10-22T11:00:00Z');
assert.equal(card.shouldUpdate(changed), true);
""")


def test_picker_editor_and_configuration_are_independent_of_other_cards() -> None:
    run_card("""
assert.ok(window.customCards.some((item) => item.type === 'smhi-winter-card'));
assert.deepEqual(Card.getStubConfig(card.hass), { entity: 'sensor.winter' });
card.hass.states['sensor.winter'].state = 'unavailable';
card.hass.states['sensor.thunder'] = { state: '20', attributes: { source_kind: 'local_thunder_probability_forecast' } };
const editor = new Editor();
editor.hass = card.hass;
editor.setConfig({ entity: 'sensor.winter' });
const rendered = JSON.stringify(editor.render());
assert.ok(rendered.includes('"include_entities":["sensor.winter"]'));
assert.equal(editor._computeLabel({ name: 'title' }), 'Rubrik');
globalThis.document = { createElement: (name) => name };
assert.equal(Card.getConfigElement(), 'smhi-winter-card-editor');
let event;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
editor.dispatchEvent = (value) => { event = value; };
editor._valueChanged({ detail: { value: { show_forecast: false } } });
assert.equal(event.type, 'config-changed');
assert.equal(event.bubbles, true);
assert.equal(event.composed, true);
assert.equal(event.detail.config.entity, 'sensor.winter');
assert.equal(event.detail.config.show_forecast, false);
assert.throws(() => card.setConfig({ entity: 'weather.home' }));
card.setConfig({ entity: '' });
assert.ok(output(card.render()).includes('Aktivera lokalt vinterväder'));
""")


def test_title_visibility_and_expansion_use_existing_forecast_controls() -> None:
    run_card("""
card.setConfig({ entity: 'sensor.winter', title: 'Vinter hemma', show_forecast: false });
assert.ok(output(card.render()).includes('Vinter hemma'));
assert.ok(!output(card.render()).includes('<details'));
card.setConfig({ entity: 'sensor.winter', forecast_expanded: true });
assert.equal(card._forecastOpen, true);
assert.ok(output(card.render()).includes('75,5 %'));
card._forecastToggled({ target: { open: false } });
card.hass = { ...card.hass };
assert.equal(card._forecastOpen, false);
""")
