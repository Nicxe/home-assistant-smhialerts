# Home Assistant - SMHI Weather Warnings & Alerts

[![Buy me a Coffee](https://img.shields.io/badge/Support-Buy%20me%20a%20coffee-fdd734?logo=buy-me-a-coffee)](ttps://www.buymeacoffee.com/NiklasV) [![Last commit](https://img.shields.io/github/last-commit/Nicxe/home-assistant-smhialerts)](#) [![Version](https://img.shields.io/github/v/release/Nicxe/home-assistant-smhialerts)](#) ![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/nicxe/home-assistant-smhialerts/latest/total)


## Overview

Easily receive and manage SMHI (Swedish Meteorological and Hydrological Institute) weather warnings and alerts directly in Home Assistant, enabling you to trigger actions or display information on your dashboard.

There is also a dashboard card specifically for this integration, which can be found here: [SMHI Alert Card](https://github.com/Nicxe/home-assistant-smhialert-card).

This custom component connects to SMHI's open API to retrieve weather alerts in Sweden, organizing the data by districts and their respective messages. You can choose to receive notifications for all districts or a specific one.

## Installation

You can install this integration as a custom repository by following one of these guides:

### With HACS (Recommended)

To install the custom component using HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=home-assistant-smhialerts&category=integration)

or
1. Install HACS if you don't have it already
2. Open HACS in Home Assistant
3. Search for "SMHI"
4. Click the download button. ⬇️


<details>
<summary>Without HACS</summary>

1. Download the latest release of the SMHI Alert integration from **[GitHub Releases](https://github.com/Nicxe/home-assistant-smhialerts/releases)**.
2. Extract the downloaded files and place the `smhi_alerts` folder in your Home Assistant `custom_components` directory (usually located in the `config/custom_components` directory).
3. Restart your Home Assistant instance to load the new integration.

</details>

## Configuration

The integration will always show SMHI warnings; however, you can choose whether to show messages or not in the configuration. A message represents a potential risk, such as a risk of water shortage.

To add the integration to your Home Assistant instance, use the button below:

> [!WARNING]
> It is not recommended to select all districts, as this may lead to the sensor generating a large amount of data. This can exceed the system's storage limits, causing performance issues and potentially resulting in incomplete information.

<p>
    <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=smhi_alerts" class="my badge" target="_blank">
        <img src="https://my.home-assistant.io/badges/config_flow_start.svg">
    </a>
</p>

### Manual Configuration

If the button above does not work, you can also perform the following steps manually:

1. Browse to your Home Assistant instance.
2. Go to **Settings > Devices & Services**.
3. In the bottom right corner, select the **Add Integration** button.
4. From the list, select **SMHI Alerts**.
5. Follow the on-screen instructions to complete the setup.

## Usage Screenshots

Using the [SMHI Alert Card](https://github.com/Nicxe/home-assistant-smhialert-card):

<img width="482" height="520" alt="smhi_alert_screenshoot" src="https://github.com/user-attachments/assets/13b65017-d315-48ae-9934-9ed8537163fa" />

