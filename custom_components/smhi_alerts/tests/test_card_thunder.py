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
const Card = elements.get('smhi-thunder-card');
const Editor = elements.get('smhi-thunder-card-editor');
const card = new Card();
card.setConfig({ entity: 'sensor.thunder' });
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


def test_zero_is_valid_at_next_timestamp_without_a_warning_sensor() -> None:
    run_card("""
delete card.hass.states['sensor.alerts'];
const data = card._thunderData();
assert.equal(data.current.probability, 0);
assert.equal(data.current.valid_time, '2026-09-04T11:00:00.000Z');
const rendered = output(card.render());
assert.ok(rendered.includes('0 %'));
assert.ok(rendered.includes('Nästa prognostid'));
assert.ok(rendered.includes('datetime=2026-09-04T11:00:00.000Z'));
assert.ok(!rendered.includes('Inga varningar'));
assert.ok(rendered.includes('Åsksannolikhet'));
assert.ok(rendered.includes('<ha-card>'));
assert.ok(rendered.includes('Prognostider · Nästa 48 timmar'));
assert.ok(!rendered.includes('intervalParametersStartTime'));
assert.equal(card.hass.states['sensor.alerts'], undefined);
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


def test_wrong_source_cannot_masquerade_as_thunder_probability() -> None:
    run_card("""
assert.ok(card.getCardSize() > 0);
card.hass.states['sensor.thunder'].attributes.source_kind = 'local_fire_risk_forecast';
assert.equal(card._thunderData(), null);
card.hass.states['sensor.thunder'] = thunder('0', { probability_unit: 'fraction' });
assert.equal(card._thunderData(), null);
delete card.hass.states['sensor.thunder'];
assert.equal(card._thunderData(), null);
assert.throws(() => card.setConfig({ entity: 'weather.home' }));
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
editor.setConfig({ entity: 'sensor.thunder' });
const rendered = JSON.stringify(editor.render());
assert.equal(editor._computeLabel({ name: 'entity' }), 'Sensor');
assert.ok(rendered.includes('"include_entities":["sensor.thunder"]'));
const includeList = rendered.match(/"include_entities":(\[[^\]]*\])/)[1];
assert.deepEqual(JSON.parse(includeList), ['sensor.thunder']);
let event;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init.detail; } };
editor.dispatchEvent = (value) => { event = value; };
editor._valueChanged({ detail: { value: { show_forecast: false } } });
assert.equal(event.detail.config.entity, 'sensor.thunder');
assert.equal(event.detail.config.show_forecast, false);
""")


def test_separate_card_registration_stubs_and_editor_events() -> None:
    run_card("""
assert.deepEqual(window.customCards.map((item) => item.type).sort(),
  ['smhi-alert-card', 'smhi-fire-risk-card', 'smhi-thunder-card']);
assert.deepEqual(Card.getStubConfig(card.hass), { entity: 'sensor.thunder' });
const fireCard = elements.get('smhi-fire-risk-card');
assert.deepEqual(fireCard.getStubConfig(card.hass), { entity: '' });
card.setConfig(Card.getStubConfig({ states: {} }));
assert.ok(output(card.render()).includes('Aktivera lokal åsksannolikhet'));
globalThis.document = { createElement: (name) => name };
assert.equal(Card.getConfigElement(), 'smhi-thunder-card-editor');
assert.equal(fireCard.getConfigElement(), 'smhi-fire-risk-card-editor');
const editor = new Editor();
editor.hass = card.hass;
editor.setConfig({ entity: 'sensor.thunder', title: 'Åska' });
let emitted;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
editor.dispatchEvent = (event) => { emitted = event; };
editor._valueChanged({ detail: { value: { show_forecast: false } } });
assert.equal(emitted.type, 'config-changed');
assert.equal(emitted.bubbles, true);
assert.equal(emitted.composed, true);
assert.deepEqual(emitted.detail.config, { entity: 'sensor.thunder', title: 'Åska', show_forecast: false });
""")


def test_warning_card_does_not_render_or_edit_local_forecasts() -> None:
    run_card("""
const Alert = elements.get('smhi-alert-card');
const alerts = new Alert();
alerts.hass = card.hass;
alerts.setConfig({ entity: 'sensor.alerts', show_header: false, show_empty_message: false,
  fire_risk_entity: 'sensor.thunder', thunder_probability_entity: 'sensor.thunder' });
assert.equal(alerts.getCardSize(), 0);
assert.ok(!output(alerts.render()).includes('Åsksannolikhet'));
assert.ok(!output(alerts.render()).includes('Lokal brandrisk'));
const changed = new Map([['hass', {}]]);
assert.equal(alerts.shouldUpdate(changed), true);
card.hass.states['sensor.thunder'].attributes.current.probability = 95;
assert.equal(alerts.shouldUpdate(changed), false);
const editor = new (elements.get('smhi-alert-card-editor'))();
editor.hass = card.hass;
editor.setConfig({ entity: 'sensor.alerts' });
const editorOutput = JSON.stringify(editor.render());
assert.ok(!editorOutput.includes('thunder_probability_entity'));
assert.ok(!editorOutput.includes('fire_risk_entity'));
""")


def test_forecast_visibility_title_and_expansion_are_independent() -> None:
    run_card("""
card.setConfig({ entity: 'sensor.thunder', title: 'Min åska', show_forecast: false });
let rendered = output(card.render());
assert.ok(rendered.includes('Min åska'));
assert.ok(rendered.includes('0 %'));
assert.ok(!rendered.includes('<details'));
card.setConfig({ entity: 'sensor.thunder', forecast_expanded: true });
assert.equal(card._forecastOpen, true);
card._forecastToggled({ target: { open: false } });
card.hass = { ...card.hass };
assert.equal(card._forecastOpen, false);
assert.ok(output(card.render()).includes('24 %'));
assert.equal(card.getGridOptions().rows, undefined);
""")


def test_forecast_clock_refresh_is_cancelled_when_card_is_removed() -> None:
    run_card("""
window.LitElement.prototype.connectedCallback = () => {};
window.LitElement.prototype.disconnectedCallback = () => {};
let tick, interval, cleared, updates = 0;
globalThis.setInterval = (callback, duration) => { tick = callback; interval = duration; return 19; };
globalThis.clearInterval = (id) => { cleared = id; };
card.requestUpdate = () => { updates++; };
card.connectedCallback();
assert.equal(interval, 60000);
tick();
assert.equal(updates, 1);
card.disconnectedCallback();
assert.equal(cleared, 19);
""")


@pytest.mark.parametrize("card_type", ["smhi-fire-risk-card", "smhi-thunder-card"])
def test_user_clock_format_overrides_language_and_handles_midnight(
    card_type: str,
) -> None:
    run_card(f"""
const forecastCard = new (elements.get({json.dumps(card_type)}))();
forecastCard.setConfig({{ entity: 'sensor.thunder' }});
forecastCard.hass = {{ ...card.hass, language: 'en', config: {{ time_zone: 'Europe/Stockholm' }},
  locale: {{ language: 'en', time_format: '24', time_zone: 'server' }} }};
assert.match(forecastCard._formatDate('2026-09-04T17:00:00Z'), /19:00/);
assert.doesNotMatch(forecastCard._formatDate('2026-09-04T17:00:00Z'), /AM|PM/);
assert.match(forecastCard._formatDate('2026-09-04T22:00:00Z'), /00:00/);
forecastCard.hass.locale.time_format = '12';
assert.match(forecastCard._formatDate('2026-09-04T17:00:00Z'), /7:00 PM/);
assert.match(forecastCard._formatDate('2026-09-04T22:00:00Z'), /12:00 AM/);
forecastCard.hass.language = 'sv';
forecastCard.hass.locale.language = 'sv';
assert.match(forecastCard._formatDate('2026-09-04T17:00:00Z'), /7:00/);
forecastCard.hass.locale.time_format = 'language';
assert.match(forecastCard._formatDate('2026-09-04T17:00:00Z'), /19:00/);
forecastCard.hass.locale.language = 'en-US';
assert.match(forecastCard._formatDate('2026-09-04T17:00:00Z'), /7:00 PM/);
""")


@pytest.mark.parametrize("card_type", ["smhi-fire-risk-card", "smhi-thunder-card"])
def test_profile_clock_changes_trigger_rendering_without_new_sensor_data(
    card_type: str,
) -> None:
    run_card(f"""
const forecastCard = new (elements.get({json.dumps(card_type)}))();
forecastCard.setConfig({{ entity: 'sensor.thunder' }});
forecastCard.hass = {{ ...card.hass, locale: {{ language: 'en', time_format: '12', time_zone: 'server' }} }};
const changed = new Map([['hass', {{}}]]);
assert.equal(forecastCard.shouldUpdate(changed), true);
assert.equal(forecastCard.shouldUpdate(changed), false);
forecastCard.hass = {{ ...forecastCard.hass, locale: {{ ...forecastCard.hass.locale, time_format: '24' }} }};
assert.equal(forecastCard.shouldUpdate(changed), true);
assert.equal(forecastCard.shouldUpdate(changed), false);
forecastCard.hass.locale.language = 'sv';
assert.equal(forecastCard.shouldUpdate(changed), true);
forecastCard.hass.locale.time_zone = 'local';
assert.equal(forecastCard.shouldUpdate(changed), true);
""")


def test_system_clock_format_uses_browser_locale_instead_of_ha_language() -> None:
    run_card("""
card.hass = { ...card.hass, language: 'sv', locale: { language: 'sv', time_format: 'system' },
  config: { time_zone: 'Europe/Stockholm' } };
const nativeDateTimeFormat = Intl.DateTimeFormat;
const locales = [];
Intl.DateTimeFormat = function(locale, options) {
  locales.push(locale);
  // Model an English browser while HA uses Swedish.
  return new nativeDateTimeFormat(locale === undefined ? 'en-US' : locale, options);
};
const formatted = card._formatDate('2026-09-04T17:00:00Z');
assert.ok(locales.includes(undefined));
assert.match(formatted, /7:00/);
assert.doesNotMatch(formatted, /19:00/);
Intl.DateTimeFormat = nativeDateTimeFormat;
""")
