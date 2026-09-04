# SMHI Alerts

[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/NiklasV) ![GitHub Release](https://img.shields.io/github/v/release/nicxe/home-assistant-smhialerts) ![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/nicxe/home-assistant-smhialerts/latest/total)

## Overview
SMHI Alerts brings weather warnings and risk messages from the Swedish Meteorological and Hydrological Institute (SMHI) into Home Assistant.

This repository now contains both:
- The Home Assistant integration (`smhi_alerts`)
- Three independent Lovelace cards for official alerts, local fire risk and thunderstorm probability (bundled in `smhi-alert-card.js`)

## Installation

### Integration with HACS (recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=home-assistant-smhialerts&category=integration)

You can also add the repository manually in HACS as type **Integration**.

### Integration without HACS
1. Download `smhi_alerts.zip` from the [latest release](https://github.com/Nicxe/home-assistant-smhialerts/releases).
2. Extract the archive and place the `smhi_alerts` folder in `config/custom_components/`.
3. Restart Home Assistant.

### Dashboard card installation
All three cards are bundled with this integration and use the same resource.

When the integration starts, it automatically:
- syncs the bundled card to `config/www/smhi-alert-card.js`
- syncs required sidecar assets (icons) to `config/www/`
- creates or updates a Lovelace `module` resource at `/local/smhi-alert-card.js?v=...` for cache-busting

If you have just installed or updated, reload the browser once to ensure the latest card resource is loaded.

## Card usage
1. Open your dashboard.
2. Select **Edit dashboard**.
3. Add a new card.
4. Choose **SMHI Alert Card**, **SMHI Fire Risk Card** or **SMHI Thunder Card**.
5. Select the sensor for that card in its visual editor.

Manual card types:
- `custom:smhi-alert-card` — official SMHI warnings and messages
- `custom:smhi-fire-risk-card` — local fire risk and daily forecasts
- `custom:smhi-thunder-card` — local thunderstorm probability and forecast times

### Map configuration
Enable **Show map (geometry)** in the card editor to display the affected warning area. The integration option **Include geometry (map polygons)** must also be enabled for the selected SMHI Alerts entry.

The card uses OpenStreetMap by default and includes the required attribution. The following optional settings are available when you want to use another XYZ tile provider:

- **Custom map tile URL**: HTTPS or same-origin URL containing `{z}`, `{x}`, and `{y}`
- **Custom map tile attribution**: attribution required by the selected provider
- **Map tile maximum zoom**: highest supported zoom level, from `0` to `22` (default `18`)

Both a custom tile URL and its attribution must be provided together. You can leave these fields empty to continue using the default OpenStreetMap tiles.

### Manual fallback (if needed)
Normally no manual Lovelace resource setup is required.

If your dashboard does not load the card automatically, add this resource manually:
- URL: `/local/smhi-alert-card.js`
- Type: `JavaScript Module`

## Configuration
To add the integration, use this button:

<p>
  <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=smhi_alerts" class="my badge" target="_blank">
    <img src="https://my.home-assistant.io/badges/config_flow_start.svg" alt="Add SMHI Alerts to Home Assistant">
  </a>
</p>

If needed, add it manually via **Settings > Devices & Services > Add Integration**.

> [!WARNING]
> It is not recommended to select all districts, as this may generate large sensor attributes and impact recorder/storage performance.

### Optional local fire risk

Open **Settings > Devices & Services > SMHI Alerts > Configure**. Enable
**Enable local fire risk forecasts** and confirm the **Fire risk location (map)** on its separate
map. This point is independent of the district or radius used for official
warnings. SMHI provides useful fire risk data for land and inland waters in Sweden;
coverage and seasonal availability vary by parameter.

The option adds three sensors to the existing device:

| Sensor | Daily forecast |
| --- | --- |
| Forest fire risk | SMHI's forest fire classification, from very low to extreme (5E) |
| Grass fire risk | Low to very high risk, or SMHI's explicit snow-covered / grass fire season over classifications |
| Forest fuel drying | Forest fuel conditions, from very wet to extremely dry (5E) |

These are **local model forecasts**, separate from issued SMHI warnings and
messages. They describe the selected day, not an observed fire or a legal burning
ban. They do not alter the existing alert sensor, active binary sensor, warning
counts or severity. The feature is off by default and needs no API key.

Add **SMHI Fire Risk Card** from the dashboard card picker and choose any of the
three fire risk sensors. This standalone card shows today's forest fire risk,
grass fire risk and fuel drying, with expandable daily forecasts. It needs only
a fire risk sensor and can be used without a warning card or thunder card.

```yaml
type: custom:smhi-fire-risk-card
entity: sensor.your_forest_fire_risk
```

The forecast covers today and up to five following days, selected using the
calendar in Sweden (including daylight saving time). The integration checks for
a newly approved forecast every 30 minutes and reuses cached point data when the
approval time is unchanged. Today's values change at Swedish midnight without
another download. Forecasts approved more than 18 hours ago become unavailable;
temporary API failures also make the fire sensors unavailable while official
warnings keep working. A missing individual class is `unknown`, never zero or
"no risk". SMHI's `-1` value does not reliably distinguish missing data from
seasonal absence.

The sensors expose `raw_class`, `forecast_date`, `valid_time`, `approved_time`,
`reference_time`, `current`, `forecast`, and the returned grid point. Forest risk
and fuel drying raw class `6` are displayed as **5E**. Grass fire uses its own
classification. Large `current` and `forecast` attributes are excluded from
recorder history. Entity IDs remain stable when the point changes or the option
is turned off and on. Turning the feature off stops its downloads; remove the
fire risk card if you no longer want to display it.

Source: [SMHI daily fire risk API](https://opendata.smhi.se/metfcst/fwif/introduction),
[parameter definitions](https://opendata.smhi.se/metfcst/fwif/parameters),
[forecast publication times](https://opendata.smhi.se/metfcst/fwif/approved_time).

### Optional local thunderstorm probability

Open **Settings > Devices & Services > SMHI Alerts > Configure**. Enable
**Enable local thunderstorm probability** and confirm its separate location on
the map. The feature is off by default, needs no API key, and can be enabled
independently of local fire risk. The selected point is independent of the
district and radius used for official warnings.

The **Thunderstorm probability** sensor reports SMHI's percentage at the **next
forecast time**, identified by its `valid_time` attribute. This is a forecast
valid at that time, not a measured lightning strike, a probability accumulated
over the coming hour, or an issued thunderstorm warning. A value of `0` is a
valid forecast; a missing probability remains `unknown`.

Add **SMHI Thunder Card** from the dashboard card picker and select the
**Thunderstorm probability** sensor. This standalone card shows the percentage
with its exact forecast time and an expandable list for the next 48 hours.
It needs only its own sensor and can be used without a warning card or fire risk
card. The forecast list scrolls when long and keeps every available forecast time.

```yaml
type: custom:smhi-thunder-card
entity: sensor.your_thunderstorm_probability
```

Both forecast cards have a visual editor with **Sensor**, **Title**, **Show forecast**
and **Expand forecast by default**. These optional settings are also available in
YAML as `title`, `show_forecast` (default `true`) and `forecast_expanded` (default
`false`). Card text follows the Home Assistant display language, with Swedish
and English translations. Times follow the user's Home Assistant profile,
including 12-hour, 24-hour, language-based or system-locale clock format and
local or server time zone. Missing data stays visibly unavailable or unknown.

If you previously added `fire_risk_entity` or `thunder_probability_entity` to
`custom:smhi-alert-card`, move each sensor to the `entity` setting of its own card
using the examples above, then remove the old fields. Local forecasts are no
longer rendered inside the alert card. The existing warning card configuration
continues to control issued warnings and messages, including official fire risk
messages and thunderstorm warnings. No additional dashboard resource is needed.

The integration uses SMHI's SNOW point forecast, checks `createdtime` every
15 minutes, and reuses point data while the source creation time is unchanged.
The next forecast time advances locally when a forecast timestamp is reached,
without requiring another download. Source data two hours old or older is
unavailable; API failures also affect only this source. Changing the location
or disabling and re-enabling the option preserves the sensor's unique ID.

Attributes include `created_time`, `reference_time`, `valid_time`, `current`,
`forecast`, `probability_unit`, the returned grid point and `data_source_url`.
Each forecast item contains `valid_time` and `probability`. Missing values are
retained at their forecast time rather than replaced by another period. The
large `current` and `forecast` attributes are excluded from recorder history.
No observation state class or long-term measurement statistics are assigned to
this predicted value.

Source: [SMHI SNOW point forecasts](https://opendata.smhi.se/metfcst/snow1gv1/get_point_forecast),
[parameter definitions](https://opendata.smhi.se/metfcst/snow1gv1/parameters).

### Development checks

Use Python 3.14 and Node.js 22 or newer. In a virtual environment, install
`requirements-test.txt`, then run:

```sh
python -m pytest -q
ruff check custom_components/smhi_alerts conftest.py
ruff format --check custom_components/smhi_alerts conftest.py
node --input-type=module --check < custom_components/smhi_alerts/www/smhi-alert-card.js
```

The regression suite mocks external requests and includes real Home Assistant
config-entry setup, options, reload and unload, API parsing/cache failures and
card behavior. The pinned test harness uses Home Assistant 2026.1.2; runtime
verification should also be performed on the target Home Assistant version.

## Release assets and versioning
Each GitHub release in this repository publishes:
- `smhi_alerts.zip` for integration installation

The bundled alert card and its assets are included inside `smhi_alerts.zip`.

## Migration from the old card repository
If you previously used `Nicxe/home-assistant-smhialert-card`, see [MIGRATION.md](./MIGRATION.md).

## Usage screenshot
<img width="482" height="520" alt="smhi_alert_screenshot" src="https://github.com/user-attachments/assets/13b65017-d315-48ae-9934-9ed8537163fa" />
