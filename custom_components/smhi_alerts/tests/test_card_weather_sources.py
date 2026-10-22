"""Exercise wind, precipitation and past analysis in the shipped card bundle."""

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
const windPoint = (time, gust) => ({ valid_time: time, gust });
const precipPoint = (start, end, probability, amount) => ({ valid_time: end, interval_start: start, probability, amount });
const analysisPoint = (time, precipitation, snow_change) => ({ valid_time: time, precipitation, snow_change });
const metadata = { created_time: '2026-10-22T10:15:00Z', reference_time: '2026-10-22T10:00:00Z' };
const wind = (state = '0', overrides = {}) => ({ state, attributes: { ...metadata,
  source_kind: 'local_wind_forecast', wind_unit: 'm/s',
  current: windPoint('2026-10-22T11:00:00Z', 0),
  forecast: [windPoint('2026-10-22T11:00:00Z', 0), windPoint('2026-10-22T12:00:00Z', 15.2)],
  max_gust_24h: 15.2, max_gust_time: '2026-10-22T12:00:00Z',
  max_window_end: '2026-10-23T10:30:00Z', max_complete: true,
  ...overrides,
}});
const precip = (state = '0', overrides = {}) => ({ state, attributes: { ...metadata,
  source_kind: 'local_precipitation_forecast', amount_unit: 'mm', probability_unit: '%',
  current: precipPoint('2026-10-22T10:00:00Z', '2026-10-22T11:00:00Z', 0, 0),
  forecast: [precipPoint('2026-10-22T10:00:00Z', '2026-10-22T11:00:00Z', 0, 0),
    precipPoint('2026-10-22T12:00:00Z', '2026-10-22T18:00:00Z', 75, 12.7)],
  ...overrides,
}});
const analysis = (state = '0', overrides = {}) => ({ state, attributes: { ...metadata,
  source_kind: 'local_weather_analysis', precipitation_unit: 'mm', snow_change_unit: 'cm',
  current: analysisPoint('2026-10-22T10:00:00Z', 0, -1.2),
  history: [analysisPoint('2026-10-22T10:00:00Z', 0, -1.2), analysisPoint('2026-10-22T09:00:00Z', 1.5, 0)],
  ...overrides,
}});
const hass = { language: 'sv', config: { time_zone: 'Europe/Stockholm',
  unit_system: { wind_speed: 'm/s', accumulated_precipitation: 'mm' } },
  locale: { language: 'sv', time_format: '24', time_zone: 'server' }, states: {
    'sensor.wind': wind(), 'sensor.precipitation': precip(), 'sensor.analysis': analysis(),
    'sensor.thunder': { state: '0', attributes: { source_kind: 'local_thunder_probability_forecast' } },
}};
const cards = {};
for (const kind of ['wind', 'precipitation', 'analysis']) {
  const card = new (elements.get(`smhi-${kind}-card`))();
  card.setConfig({ entity: `sensor.${kind}` });
  card.hass = hass;
  card._weatherNow = () => Date.parse('2026-10-22T10:30:00Z');
  cards[kind] = card;
}
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


def test_wind_preserves_zero_and_maximum_with_exact_times() -> None:
    run_card("""
const rendered = output(cards.wind.render());
assert.ok(rendered.includes('Vindbyar'));
assert.ok(rendered.includes('0 m/s'));
assert.ok(rendered.includes('15,2 m/s'));
assert.ok(rendered.includes('datetime=2026-10-22T11:00:00.000Z'));
assert.ok(rendered.includes('datetime=2026-10-22T12:00:00.000Z'));
assert.ok(rendered.includes('Högsta prognosvärde · Nästa 24 timmar'));
assert.ok(rendered.includes('Perioden slutar'));
assert.ok(!rendered.includes('varning'));
""")


def test_incomplete_or_expired_maximum_never_appears_as_a_reliable_peak() -> None:
    run_card("""
hass.states['sensor.wind'] = wind('0', { max_complete: false });
assert.equal(cards.wind._sourceData().maximum, null);
const summary = output(cards.wind._sourceCurrent(cards.wind._sourceData()));
assert.ok(summary.includes('0 m/s'));
assert.ok(summary.includes('Data saknas'));
assert.ok(!summary.includes('15,2 m/s'));
hass.states['sensor.wind'] = wind('0', { max_gust_time: '2026-10-22T10:00:00Z' });
assert.equal(cards.wind._sourceData().maximum, null);
hass.states['sensor.wind'] = wind('0', { max_gust_time: '2026-10-23T11:00:00Z' });
assert.equal(cards.wind._sourceData().maximum, null);
""")


def test_precipitation_totals_always_display_both_interval_bounds() -> None:
    run_card("""
const rendered = output(cards.precipitation.render());
assert.ok(rendered.includes('0 %'));
assert.ok(rendered.includes('0 mm'));
assert.ok(rendered.includes('12,7 mm'));
assert.ok(rendered.includes('datetime=2026-10-22T12:00:00.000Z'));
assert.ok(rendered.includes('datetime=2026-10-22T18:00:00.000Z'));
assert.ok(rendered.includes('för hela det angivna intervallet'));
assert.ok(rendered.includes('Sannolikhet för minst 0,1 mm'));
assert.ok(!rendered.includes('nästa timme'));
assert.ok(!rendered.includes('mm/h'));
""")


@pytest.mark.parametrize(
    "start", [None, "invalid", "2026-10-22", "2026-10-22T12:00:00Z"]
)
def test_invalid_interval_does_not_display_amount_or_probability(
    start: str | None,
) -> None:
    run_card(f"""
hass.states['sensor.precipitation'] = precip('0', {{ current:
  precipPoint({json.dumps(start)}, '2026-10-22T11:00:00Z', 90, 7),
}});
const data = cards.precipitation._sourceData();
assert.equal(data.current.amount, null);
assert.equal(data.current.probability, null);
const rendered = output(cards.precipitation._sourceCurrent(data));
assert.ok(rendered.includes('Intervallet saknas'));
assert.ok(!rendered.includes('90 %'));
assert.ok(!rendered.includes('7 mm'));
""")


def test_analysis_shows_past_one_hour_interval_and_signed_snow_change() -> None:
    run_card("""
const rendered = output(cards.analysis.render());
assert.ok(rendered.includes('Väderanalys'));
assert.ok(rendered.includes('MESAN-analys'));
assert.ok(rendered.includes('Analyserat intervall · 1 timme'));
assert.ok(rendered.includes('datetime=2026-10-22T09:00:00.000Z'));
assert.ok(rendered.includes('datetime=2026-10-22T10:00:00.000Z'));
assert.ok(rendered.includes('0 mm'));
assert.ok(rendered.includes('−1,2 cm'));
assert.ok(rendered.includes('Snömängdens förändring · Senaste timmen'));
assert.ok(rendered.includes('Analyshistorik · Senaste 24 timmarna'));
assert.ok(!rendered.includes('snödjup'));
assert.ok(!rendered.includes('nysnö'));
assert.ok(!rendered.includes('Prognostider'));
assert.ok(!rendered.includes('Uppmätt'));
""")


def test_forecast_and_history_keep_their_own_windows_and_sort_direction() -> None:
    run_card("""
hass.states['sensor.wind'] = wind('0', { forecast: [
  windPoint('2026-10-22T13:00:00Z', 5), windPoint('2026-10-22T10:30:00Z', 20),
  windPoint('2026-10-22T11:00:00Z', 0), windPoint('2026-10-22T13:00:00+02:00', 0),
  windPoint('2026-10-24T10:30:00Z', 10), windPoint('2026-10-24T11:00:00Z', 99),
  windPoint('2026-10-22', 10), windPoint('bad', 10),
] });
assert.deepEqual(cards.wind._sourceData().series.map((row) => row.valid_time), [
  '2026-10-22T11:00:00.000Z', '2026-10-22T13:00:00.000Z', '2026-10-24T10:30:00.000Z',
]);
hass.states['sensor.analysis'] = analysis('0', { history: [
  analysisPoint('2026-10-22T09:00:00Z', 1, 0), analysisPoint('2026-10-22T10:00:00Z', 0, -1),
  analysisPoint('2026-10-22T11:00:00Z', 3, 1), analysisPoint('2026-10-21T10:00:00Z', 2, 1),
  analysisPoint('2026-10-22', 2, 1),
] });
assert.deepEqual(cards.analysis._sourceData().series.map((row) => row.valid_time), [
  '2026-10-22T10:00:00.000Z', '2026-10-22T09:00:00.000Z',
]);
""")


def test_unknown_selected_sensor_retains_sibling_values_at_the_same_time() -> None:
    run_card("""
hass.states['sensor.precipitation'] = precip('unknown', { current:
  precipPoint('2026-10-22T10:00:00Z', '2026-10-22T11:00:00Z', null, 2.5),
});
const precipRendered = output(cards.precipitation.render());
assert.ok(precipRendered.includes('Data saknas'));
assert.ok(precipRendered.includes('2,5 mm'));
assert.equal(cards.precipitation._sourceData().current.valid_time, '2026-10-22T11:00:00.000Z');
hass.states['sensor.analysis'] = analysis('unknown', { current: analysisPoint('2026-10-22T10:00:00Z', null, -2) });
assert.ok(output(cards.analysis.render()).includes('−2 cm'));
assert.ok(output(cards.analysis.render()).includes('Data saknas'));
hass.states['sensor.wind'] = wind('unknown', { current: windPoint('2026-10-22T11:00:00Z', null) });
assert.equal(cards.wind._sourceData().current.gust, null);
assert.equal(cards.wind._sourceData().maximum, 15.2);
""")


@pytest.mark.parametrize("kind", ["wind", "precipitation", "analysis"])
def test_unavailable_wrong_source_units_and_stale_data_never_show_cached_values(
    kind: str,
) -> None:
    run_card(f"""
const kind = {json.dumps(kind)};
const card = cards[kind];
const source = hass.states[`sensor.${{kind}}`];
source.state = 'unavailable';
assert.equal(card._sourceData(), null);
source.state = '0';
source.attributes.source_kind = 'local_winter_forecast';
assert.equal(card._sourceData(), null);
source.attributes.source_kind = {{ wind: 'local_wind_forecast', precipitation: 'local_precipitation_forecast', analysis: 'local_weather_analysis' }}[kind];
source.attributes.created_time = '2026-10-22T06:00:00Z';
assert.equal(card._sourceData(), null);
source.attributes.created_time = '2026-10-22T11:00:00Z';
assert.equal(card._sourceData(), null);
source.attributes.created_time = '2026-10-22T10:15:00Z';
source.attributes[{{ wind: 'wind_unit', precipitation: 'amount_unit', analysis: 'snow_change_unit' }}[kind]] = 'invalid';
assert.equal(card._sourceData(), null);
""")


def test_canonical_units_follow_ha_preferences_without_reusing_converted_states() -> (
    None
):
    run_card("""
hass.config.unit_system.wind_speed = 'km/h';
assert.equal(cards.wind._windValue(10), '36 km/h');
hass.config.unit_system.wind_speed = 'mph';
assert.equal(cards.wind._windValue(10), '22,4 mph');
hass.config.unit_system.wind_speed = 'kn';
assert.equal(cards.wind._windValue(10), '19,4 kn');
hass.config.unit_system.accumulated_precipitation = 'in';
assert.equal(cards.precipitation._precipitationValue(25.4), '1 in');
assert.equal(cards.precipitation._precipitationValue(0.01), '0,0004 in');
assert.equal(cards.analysis._snowChangeValue(-2.54), '−1 in');
hass.states['sensor.precipitation'].state = '999';
assert.equal(cards.precipitation._sourceData().current.amount, 0);
const changed = new Map([['hass', {}]]);
assert.equal(cards.wind.shouldUpdate(changed), true);
assert.equal(cards.wind.shouldUpdate(changed), false);
hass.config.unit_system.wind_speed = 'm/s';
assert.equal(cards.wind.shouldUpdate(changed), true);
""")


def test_untrusted_forecast_values_are_unknown_and_text_is_escaped() -> None:
    run_card("""
for (const value of [null, true, false, '', '1', [], {}, 9999, -1, NaN, Infinity, '<img onerror=alert(1)>']) {
  assert.equal(cards.wind._sourceNumber(value), null);
}
assert.equal(cards.wind._sourceNumber(0), 0);
assert.equal(cards.analysis._sourceNumber(-1, -Number.MAX_VALUE), -1);
assert.equal(cards.precipitation._sourcePoint(precipPoint('2026-10-22T10:00:00Z', '2026-10-22T11:00:00Z', 101, true), Date.parse('2026-10-22T10:30:00Z')).probability, null);
cards.wind.setConfig({ entity: 'sensor.wind', title: '<img onerror=alert(1)>' });
const rendered = output(cards.wind.render());
assert.ok(rendered.includes('&lt;img'));
assert.ok(!rendered.includes('<img'));
""")


@pytest.mark.parametrize("kind", ["wind", "precipitation", "analysis"])
def test_registration_source_picker_controls_and_localization(kind: str) -> None:
    run_card(f"""
const kind = {json.dumps(kind)};
const Card = elements.get(`smhi-${{kind}}-card`);
assert.ok(window.customCards.some((item) => item.type === `smhi-${{kind}}-card`));
assert.deepEqual(Card.getStubConfig(hass), {{ entity: `sensor.${{kind}}` }});
hass.states[`sensor.${{kind}}`].state = 'unavailable';
const editor = new (elements.get(`smhi-${{kind}}-card-editor`))();
editor.hass = hass;
editor.setConfig({{ entity: `sensor.${{kind}}`, title: 'Custom' }});
const rendered = JSON.stringify(editor.render());
assert.ok(rendered.includes(`"include_entities":["sensor.${{kind}}"]`));
assert.equal(editor._computeLabel({{ name: 'show_forecast' }}), kind === 'analysis' ? 'Visa historik' : 'Visa prognos');
assert.equal(editor._computeLabel({{ name: 'forecast_expanded' }}), kind === 'analysis' ? 'Visa historiken utfälld från början' : 'Visa prognosen utfälld från början');
let emitted;
globalThis.CustomEvent = class {{ constructor(type, init) {{ this.type = type; Object.assign(this, init); }} }};
editor.dispatchEvent = (event) => {{ emitted = event; }};
editor._valueChanged({{ detail: {{ value: {{ show_forecast: false }} }} }});
assert.equal(emitted.type, 'config-changed');
assert.equal(emitted.bubbles, true);
assert.equal(emitted.composed, true);
assert.equal(emitted.detail.config.entity, `sensor.${{kind}}`);
assert.equal(emitted.detail.config.show_forecast, false);
globalThis.document = {{ createElement: (name) => name }};
assert.equal(Card.getConfigElement(), `smhi-${{kind}}-card-editor`);
hass.language = 'en';
assert.equal(editor._computeLabel({{ name: 'show_forecast' }}), kind === 'analysis' ? 'Show history' : 'Show forecast');
cards[kind].setConfig({{ entity: '' }});
assert.ok(output(cards[kind].render()).includes('Enable local'));
""")


def test_forecast_and_analysis_visibility_title_and_expansion_are_independent() -> None:
    run_card("""
for (const [kind, card] of Object.entries(cards)) {
  card.setConfig({ entity: `sensor.${kind}`, title: 'Custom', show_forecast: false });
  assert.ok(output(card.render()).includes('Custom'));
  assert.ok(!output(card.render()).includes('<details'));
  card.setConfig({ entity: `sensor.${kind}`, forecast_expanded: true });
  assert.equal(card._forecastOpen, true);
  assert.ok(output(card.render()).includes('<details'));
  card._forecastToggled({ target: { open: false } });
  assert.equal(card._forecastOpen, false);
}
""")
