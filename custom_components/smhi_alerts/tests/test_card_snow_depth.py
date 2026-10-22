"""Exercise optional observed snow depth in the shipped winter card."""

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
card.setConfig({ entity: 'sensor.winter', snow_depth_entity: 'sensor.snow' });
card._winterNow = () => Date.parse('2026-10-22T10:30:00Z');
const snow = (state = '0', overrides = {}) => ({ state, attributes: {
  source_kind: 'snow_depth_observation', depth_cm: 0, unit_of_measurement: 'cm',
  station_name: 'Askim D', station_id: '72620', distance_km: 7.2,
  observation_time: '2026-10-22T06:00:00Z', quality: 'G', snow_cover: null,
  parameter: '8', expires_at: '2026-10-23T18:00:00Z', stale: false,
  ...overrides,
}});
card.hass = { language: 'sv', config: { time_zone: 'Europe/Stockholm' },
  locale: { language: 'sv', time_format: '24', time_zone: 'server' }, states: {
    'sensor.snow': snow(),
    'sensor.other_snow': snow('50', { depth_cm: 50, station_name: 'Another station' }),
    'sensor.winter': { state: 'unavailable', attributes: { source_kind: 'local_winter_forecast' } },
}};
"""


def run_card(script: str) -> None:
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


def test_optional_section_never_guesses_a_station_or_other_entry() -> None:
    run_card("""
card.setConfig({ entity: 'sensor.winter' });
assert.equal(card._snowDepthData(), null);
assert.ok(!output(card.render()).includes('Uppmätt snödjup'));
assert.ok(!output(card.render()).includes('Askim'));
card.setConfig({ entity: 'sensor.winter', snow_depth_entity: 'sensor.missing' });
assert.equal(card._snowDepthData().status, 'unavailable');
assert.ok(output(card.render()).includes('Snödjup är inte tillgängligt'));
assert.ok(!output(card.render()).includes('Another station'));
card.setConfig({ entity: 'sensor.winter', snow_depth_entity: '   ' });
assert.equal(card._snowDepthData(), null);
assert.throws(() => card.setConfig({ entity: 'sensor.winter', snow_depth_entity: 'weather.home' }));
""")


def test_measured_zero_is_distinct_and_forecast_outage_does_not_hide_it() -> None:
    run_card("""
const rendered = output(card.render());
assert.ok(rendered.includes('Vinterväder är inte tillgängligt'));
assert.ok(rendered.includes('Uppmätt snödjup'));
assert.ok(rendered.includes('0 cm'));
assert.ok(rendered.includes('Station: Askim D'));
assert.ok(rendered.includes('7,2 km'));
assert.ok(rendered.includes('datetime=2026-10-22T06:00:00.000Z'));
assert.ok(rendered.includes('08:00'));
assert.ok(rendered.includes('Kontrollerat och godkänt'));
assert.ok(!rendered.includes('Another station'));
// The canonical centimetres stay correct even if HA converts the sensor state.
card.hass.states['sensor.snow'] = snow('0.3937', { depth_cm: 1, unit_of_measurement: 'in' });
assert.ok(output(card.render()).includes('1 cm'));
""")


@pytest.mark.parametrize("state", ["unknown", "unavailable"])
def test_unknown_and_unavailable_never_display_cached_numeric_depth(state: str) -> None:
    run_card(f"""
card.hass.states['sensor.snow'] = snow({json.dumps(state)}, {{ depth_cm: 25 }});
const rendered = output(card._renderSnowDepth());
assert.ok(!rendered.includes('25 cm'));
assert.ok(!rendered.includes('0 cm'));
assert.ok(rendered.includes({json.dumps("Snödjupsvärde saknas" if state == "unknown" else "Snödjup är inte tillgängligt")}));
assert.ok(rendered.includes('Askim D'));
""")


@pytest.mark.parametrize("cover", ["trace", "patchy"])
def test_special_snow_cover_is_textual_and_never_negative_depth(cover: str) -> None:
    expected = "Mindre än 0,5 cm snö" if cover == "trace" else "Fläckvis snötäckt mark"
    run_card(f"""
card.hass.states['sensor.snow'] = snow('unknown', {{ depth_cm: null, snow_cover: {json.dumps(cover)} }});
assert.equal(card._snowDepthData().status, 'fresh');
const rendered = output(card._renderSnowDepth());
assert.ok(rendered.includes({json.dumps(expected)}));
assert.ok(!rendered.includes('-1 cm'));
assert.ok(!rendered.includes('-2 cm'));
""")


def test_expiry_and_network_failures_never_show_old_cover_or_depth() -> None:
    run_card("""
for (const update of [
  { stale: true }, { expires_at: '2026-10-22T10:30:00Z' },
  { expires_at: '2026-10-22T10:00:00Z' },
]) {
  card.hass.states['sensor.snow'] = snow('12', { depth_cm: 12, snow_cover: 'patchy', ...update });
  assert.equal(card._snowDepthData().status, 'stale');
  const rendered = output(card._renderSnowDepth());
  assert.ok(rendered.includes('Snödjupsmätningen är inaktuell'));
  assert.ok(!rendered.includes('12 cm'));
  assert.ok(!rendered.includes('Fläckvis snötäckt mark'));
}
card.hass.states['sensor.snow'] = snow('unavailable', { depth_cm: 12, snow_cover: 'trace' });
assert.equal(card._snowDepthData().status, 'unavailable');
assert.ok(!output(card._renderSnowDepth()).includes('Mindre än'));
""")


def test_quality_and_missing_timestamps_cannot_masquerade_as_valid_depth() -> None:
    run_card("""
for (const quality of ['Y', 'bad', null]) {
  card.hass.states['sensor.snow'] = snow('12', { depth_cm: 12, quality });
  assert.equal(card._snowDepthData().depth, null);
  assert.ok(!output(card._renderSnowDepth()).includes('12 cm'));
}
card.hass.states['sensor.snow'] = snow('unknown', { quality: 'Y' });
assert.ok(output(card._renderSnowDepth()).includes('Okontrollerat eller misstänkt'));
for (const update of [{ observation_time: null }, { expires_at: null }, { observation_time: '2026-10-22' }]) {
  card.hass.states['sensor.snow'] = snow('12', { depth_cm: 12, ...update });
  assert.equal(card._snowDepthData().status, 'unknown');
  assert.ok(!output(card._renderSnowDepth()).includes('12 cm'));
}
""")


def test_only_selected_snow_sensor_changes_trigger_rendering() -> None:
    run_card("""
const changed = new Map([['hass', {}]]);
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.other_snow'].attributes.depth_cm = 70;
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.snow'].attributes.depth_cm = 2;
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.snow'].attributes.quality = 'Y';
assert.equal(card.shouldUpdate(changed), true);
card.hass.states['sensor.snow'].state = 'unavailable';
assert.equal(card.shouldUpdate(changed), true);
""")


def test_station_values_are_escaped_and_quality_is_localized() -> None:
    run_card("""
const attack = '<img onerror=alert(1)>';
card.hass.states['sensor.snow'] = snow('0', { station_name: attack, quality: 'Y' });
const rendered = output(card._renderSnowDepth());
assert.ok(rendered.includes('&lt;img'));
assert.ok(!rendered.includes('<img'));
assert.ok(rendered.includes('Okontrollerat eller misstänkt'));
card.hass.language = 'en';
card.hass.locale.language = 'en';
card.hass.locale.time_format = '12';
assert.ok(output(card._renderSnowDepth()).includes('Measured snow depth'));
assert.ok(output(card._renderSnowDepth()).includes('Unchecked or suspect'));
assert.ok(output(card._renderSnowDepth()).includes('8:00 AM'));
card.hass.states['sensor.snow'] = snow('unknown', { depth_cm: null, snow_cover: 'patchy' });
assert.ok(output(card._renderSnowDepth()).includes('Patchy snow cover'));
""")


def test_editor_has_optional_explicit_source_picker_and_preserves_forecast() -> None:
    run_card("""
card.hass.states['sensor.snow'].state = 'unavailable';
const editor = new Editor();
editor.hass = card.hass;
editor.setConfig({ entity: 'sensor.winter', snow_depth_entity: 'sensor.snow', show_forecast: false });
const rendered = JSON.stringify(editor.render());
assert.ok(rendered.includes('"name":"snow_depth_entity"'));
assert.ok(rendered.includes('"include_entities":["sensor.snow","sensor.other_snow"]'));
assert.ok(!rendered.includes('"name":"snow_depth_entity","required":true'));
assert.equal(editor._computeLabel({ name: 'snow_depth_entity' }), 'Snödjupssensor (valfri)');
let emitted;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
editor.dispatchEvent = (event) => { emitted = event; };
editor._valueChanged({ detail: { value: { snow_depth_entity: '' } } });
assert.equal(emitted.detail.config.entity, 'sensor.winter');
assert.equal(emitted.detail.config.show_forecast, false);
assert.equal(emitted.detail.config.snow_depth_entity, '');
const ThunderEditor = elements.get('smhi-thunder-card-editor');
const thunderEditor = new ThunderEditor();
thunderEditor.hass = card.hass;
thunderEditor.setConfig({ entity: 'sensor.thunder' });
assert.ok(!JSON.stringify(thunderEditor.render()).includes('"name":"snow_depth_entity"'));
""")
