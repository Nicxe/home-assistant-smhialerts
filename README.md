# SMHI Alerts

[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](https://www.buymeacoffee.com/NiklasV) ![GitHub Release](https://img.shields.io/github/v/release/nicxe/home-assistant-smhialerts) ![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/nicxe/home-assistant-smhialerts/latest/total)

## Overview
SMHI Alerts brings weather warnings and risk messages from the Swedish Meteorological and Hydrological Institute (SMHI) into Home Assistant.

This repository now contains both:
- The Home Assistant integration (`smhi_alerts`)
- The Lovelace alert card (`smhi-alert-card.js`)

## Installation

### Integration with HACS (recommended)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=home-assistant-smhialerts&category=integration)

You can also add the repository manually in HACS as type **Integration**.

### Integration without HACS
1. Download `smhi_alerts.zip` from the [latest release](https://github.com/Nicxe/home-assistant-smhialerts/releases).
2. Extract the archive and place the `smhi_alerts` folder in `config/custom_components/`.
3. Restart Home Assistant.

### Alert card installation
The alert card is bundled with this integration.

When the integration starts, it automatically:
- syncs the bundled card to `config/www/smhi-alert-card.js`
- syncs required sidecar assets (icons) to `config/www/`
- creates or updates a Lovelace `module` resource at `/local/smhi-alert-card.js?v=...` for cache-busting

If you have just installed or updated, reload the browser once to ensure the latest card resource is loaded.

## Card usage
1. Open your dashboard.
2. Select **Edit dashboard**.
3. Add a new card.
4. Choose **Custom: SMHI Alert Card**.

Manual card type:
- `custom:smhi-alert-card`

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

## Release assets and versioning
Each GitHub release in this repository publishes:
- `smhi_alerts.zip` for integration installation

The bundled alert card and its assets are included inside `smhi_alerts.zip`.

## Migration from the old card repository
If you previously used `Nicxe/home-assistant-smhialert-card`, see [MIGRATION.md](./MIGRATION.md).

## Usage screenshot
<img width="482" height="520" alt="smhi_alert_screenshot" src="https://github.com/user-attachments/assets/13b65017-d315-48ae-9934-9ed8537163fa" />
