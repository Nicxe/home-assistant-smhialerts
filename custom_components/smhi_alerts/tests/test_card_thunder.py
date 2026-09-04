"""Test the actual thunderstorm card behavior with the SMHI sensor contract."""

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
card.setConfig({ entity: 'sensor.alerts', thunder_probability_entity: 'sensor.thunder' });
card._thunderNow = () => Date.parse('2026-09-04T10:30:00Z');
const point = (time, probability) => ({ valid_time: time, probability });
const thunder = (state = '0', overrides = {}) => ({
  state, attributes: {
    source_kind: 'local_thunder_probability_forecast', probability_unit: '%', unit_of_measurement: '%',
    created_time: '2026-09-04T10:00:00Z', reference_time: '2026-09-04T06:00:00Z',
    current: point('2026-09-04T11:00:00Z', 0),
    forecast: [point('2026-09-04T11:00:00Z', 0), point('2026-09-04T12:00:00Z', 24), point('2026-09-04T13:00:00Z', null)],
    ...overrides,
  },
});
card.hass = { language: 'sv-SE', states: {
  'sensor.alerts': { state: 'Inga varningar', attributes: { messages: [], highest_severity: 'NONE', alerts_count: 0 } },
  'sensor.thunder': thunder(),
}};
"""


def run_card(script: str) -> None:
    """Execute the card module and return clear JavaScript assertion failures."""
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


def test_zero_is_valid_at_next_timestamp_without_changing_official_alerts() -> None:
    run_card("""
const before = JSON.stringify(card.hass.states['sensor.alerts']);
const data = card._thunderData();
assert.equal(data.current.probability, 0);
assert.equal(data.current.valid_time, '2026-09-04T11:00:00.000Z');
const rendered = output(card.render());
assert.ok(rendered.includes('0 %'));
assert.ok(rendered.includes('Nästa prognostid'));
assert.ok(rendered.includes('datetime=2026-09-04T11:00:00.000Z'));
assert.ok(rendered.indexOf('Inga varningar') < rendered.indexOf('Åsksannolikhet'));
assert.ok(rendered.includes('Prognostider · Nästa 48 timmar'));
assert.ok(!rendered.includes('intervalParametersStartTime'));
assert.equal(JSON.stringify(card.hass.states['sensor.alerts']), before);
""")


@pytest.mark.parametrize(
    "state", ["unavailable", "", "bad", "NaN", "Infinity", "-1", "9999", "101"]
)
def test_invalid_or_unavailable_state_does_not_display_cached_probability(
    state: str,
) -> None:
    run_card(f"""
card.hass.states['sensor.thunder'].state = {json.dumps(state)};
assert.equal(card._thunderData(), null);
const rendered = output(card._renderThunderProbability());
assert.ok(rendered.includes('Åsksannolikhet är inte tillgänglig'));
assert.ok(!rendered.includes('0 %'));
assert.ok(!rendered.includes('24 %'));
""")


def test_unknown_nearest_time_is_not_replaced_by_later_known_probability() -> None:
    run_card("""
card.hass.states['sensor.thunder'] = thunder('unknown', {
  current: point('2026-09-04T11:00:00Z', null),
  forecast: [point('2026-09-04T11:00:00Z', null), point('2026-09-04T12:00:00Z', 75)],
});
const data = card._thunderData();
assert.equal(data.current.probability, null);
assert.equal(data.current.valid_time, '2026-09-04T11:00:00.000Z');
const rendered = output(card._renderThunderProbability());
assert.ok(rendered.includes('thunder-value thunder-unknown'));
assert.ok(rendered.includes('Data saknas'));
assert.ok(rendered.includes('75 %'));
assert.ok(!rendered.includes('0 %'));
""")


def test_forecast_uses_timestamps_and_real_48_hour_window() -> None:
    run_card("""
card.hass.states['sensor.thunder'] = thunder('0', { forecast: [
  point('2026-09-04T13:00:00Z', 20), point('2026-09-04T10:00:00Z', 100),
  point('2026-09-04T12:00:00+02:00', 100), point('2026-09-04T10:30:00Z', 50),
  point('2026-09-04T11:00:00Z', 0), point('2026-09-04T13:00:00+02:00', 0),
  point('2026-09-06T10:30:00Z', 10), point('2026-09-06T11:00:00Z', 95),
  point('not a date', 80), point('2026-09-04', 90), {},
] });
assert.deepEqual(card._thunderData().forecast, [
  point('2026-09-04T11:00:00.000Z', 0), point('2026-09-04T13:00:00.000Z', 20), point('2026-09-06T10:30:00.000Z', 10),
]);
card._thunderNow = () => Date.parse('2026-09-04T11:00:00Z');
assert.equal(card._thunderData().current, null);
assert.ok(output(card._renderThunderProbability()).includes('Åsksannolikhet är inte tillgänglig'));
""")


def test_percent_ranges_and_untrusted_values() -> None:
    run_card("""
for (const value of [null, undefined, true, false, '', [], {}, -9, 9999, 100.1, NaN, Infinity, '<img onerror=alert(1)>']) {
  assert.equal(card._thunderPercent(value), null);
}
assert.equal(card._thunderPercent(0), 0);
assert.equal(card._thunderPercent('100'), 100);
assert.equal(card._thunderLabel(12.5), '12,5 %');
card.hass.states['sensor.thunder'] = thunder('unknown', {
  current: point('2026-09-04T11:00:00Z', '<img onerror=alert(1)>'),
  forecast: [point('2026-09-04T12:00:00Z', '<img onerror=alert(1)>')],
});
assert.ok(!output(card._renderThunderProbability()).includes('onerror'));
card.hass.language = 'en';
assert.equal(card._thunderLabel(null), 'No data');
assert.equal(card._thunderLabel(12.5), '12.5 %');
assert.ok(output(card._renderThunderProbability()).includes('Next forecast time'));
""")


def test_higher_resolution_keeps_every_forecast_time_in_48_hour_window() -> None:
    run_card("""
const start = Date.parse('2026-09-04T11:00:00Z');
const forecast = Array.from({ length: 96 }, (_, index) => point(
  new Date(start + index * 30 * 60 * 1000).toISOString(), index % 101,
));
card.hass.states['sensor.thunder'] = thunder('0', { forecast });
const data = card._thunderData();
assert.equal(data.forecast.length, 96);
assert.deepEqual(data.forecast, forecast);
assert.equal(data.forecast.at(-1).valid_time, '2026-09-06T10:30:00.000Z');
""")


def test_optional_source_and_wrong_source_do_not_change_existing_card_behavior() -> (
    None
):
    run_card("""
card.setConfig({ entity: 'sensor.alerts', show_header: false, show_empty_message: false });
assert.equal(card.getCardSize(), 0);
assert.ok(!output(card.render()).includes('Åsksannolikhet'));
card.setConfig({ entity: 'sensor.alerts', thunder_probability_entity: 'sensor.thunder', show_header: false, show_empty_message: false });
assert.equal(card.getCardSize(), 3);
card.hass.states['sensor.thunder'].attributes.source_kind = 'local_fire_risk_forecast';
assert.equal(card._thunderData(), null);
card.hass.states['sensor.thunder'] = thunder('0', { probability_unit: 'fraction' });
assert.equal(card._thunderData(), null);
delete card.hass.states['sensor.thunder'];
assert.equal(card._thunderData(), null);
assert.throws(() => card.setConfig({ entity: 'sensor.alerts', thunder_probability_entity: 'weather.home' }));
""")


def test_probability_only_updates_and_expired_timestamps_trigger_rendering() -> None:
    run_card("""
const changed = new Map([['hass', {}]]);
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.thunder'].attributes.forecast[1].probability = 42;
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card.hass.states['sensor.thunder'].state = 'unavailable';
assert.equal(card.shouldUpdate(changed), true);
assert.equal(card.shouldUpdate(changed), false);
card._thunderNow = () => Date.parse('2026-09-04T11:00:00Z');
assert.equal(card.shouldUpdate(changed), true);
""")


def test_editor_limits_picker_to_source_including_unavailable_sensor() -> None:
    run_card(r"""
card.hass.states['sensor.thunder'].state = 'unavailable';
card.hass.states['sensor.rain'] = { state: '20', attributes: { unit_of_measurement: '%' } };
const editor = new Editor();
editor.hass = card.hass;
editor.setConfig({ entity: 'sensor.alerts', thunder_probability_entity: 'sensor.thunder' });
const rendered = JSON.stringify(editor.render());
assert.ok(rendered.includes('Åsksannolikhetssensor (valfri)'));
assert.ok(rendered.includes('"include_entities":["sensor.thunder"]'));
const includeList = rendered.match(/"include_entities":(\[[^\]]*\])/)[1];
assert.deepEqual(JSON.parse(includeList), ['sensor.thunder']);
let event;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
editor.dispatchEvent = (value) => { event = value; };
editor._valueChanged({ detail: { value: { thunder_probability_entity: '' } } });
assert.equal(event.detail.config.entity, 'sensor.alerts');
assert.equal(event.detail.config.thunder_probability_entity, '');
""")
