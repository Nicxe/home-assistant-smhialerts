# Home Assistant - SMHI Weather Warnings & Alerts

## Overview

Easily receive and manage SMHI (Swedish Meteorological and Hydrological Institute) weather warnings and alerts directly in Home Assistant, enabling you to trigger actions or display information on your dashboard.

There is also a dashboard card specifically for this integration, which can be found here: [SMHI Alert Card](https://github.com/Nicxe/home-assistant-smhialert-card).

This custom component connects to SMHI's open API to retrieve weather alerts in Sweden, organizing the data by districts and their respective messages. You can choose to receive notifications for all districts or for a specific one.

*Based on [SMHI Alert Card](https://github.com/Lallassu/smhialert)*

## Installation

You can install this integration as a custom repository by following one of these guides:

### With HACS (Recommended)

To install the custom component in HACS use this button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nicxe&repository=home-assistant-smhialerts&category=integration)

1. Click on the three dots in the top right corner of the HACS overview menu.
2. Select **Custom repositories**.
3. Add the URL to the repository: `https://github.com/Nicxe/home-assistant-smhialerts`.
4. Select type: **Integration**.
5. Click the **ADD** button.

### Without HACS

1. Download the latest release of the SMHI Alert integration from **[GitHub Releases](https://github.com/Nicxe/home-assistant-smhialerts/releases)**.
2. Extract the downloaded files and place the `smhi_alerts` folder in your Home Assistant `custom_components` directory (usually located in the `config/custom_components` directory).
3. Restart your Home Assistant instance to load the new integration.


## Configuration

To add the integration to your Home Assistant instance, use the button below

> [!WARNING]
> It is not recommended to select all districts as this may lead to the sensor to generate a large amount of data if all districts are selected, which may exceed the system's storage limits. This can lead to performance issues and cause the data to not be stored properly, potentially resulting in incomplete information.. This can cause database performance issues; attributes will not be stored.

<p>
    <a href="https://my.home-assistant.io/redirect/config_flow_start?domain=smhi_alerts" class="my badge" target="_blank">
        <img src="https://my.home-assistant.io/badges/config_flow_start.svg">
    </a>
</p>


### Manual Configuration

If the above My button doesn’t work, you can also perform the following steps manually:

1. Browse to your Home Assistant instance.
2. Go to **Settings > Devices & Services**.
3. In the bottom right corner, select the **Add Integration** button.
4. From the list, select **SMHI Alerts**.
5. Follow the instructions on the screen to complete the setup.


## Available districts:

```
1   Stockholms län
3   Uppsala län
4   Södermanlands län
5   Östergötlands län
6   Jönköpings län
7   Kronobergs län
8   Kalmar län
9   Gotlands län
10  Blekinge län
12  Skåne län
13  Hallands län
14  Västra Götalands län
17  Värmlands län
18  Örebro län
19  Västmanlands län
20  Dalarnas län
21  Gävleborgs län
22  Västernorrlands län
23  Jämtlands län
24  Västerbottens län
25  Norrbottens län
41  Bottenviken
42  Norra Kvarken
43  Norra Bottenhavet
44  Södra Bottenhavet
45  Ålands hav
46  Skärgårdshavet
47  Finska Viken
48  Norra Östersjön
49  Mellersta Östersjön
50  Rigabukten
51  Sydöstra Östersjön
52  Södra Östersjön
53  Sydvästra Östersjön
54  Bälten
55  Öresund
56  Kattegatt
57  Skagerrak
58  Vänern
all Alla district (Not recommended)
```

## Usage Screenshots

Using the [SMHI Alert Card](https://github.com/Nicxe/home-assistant-smhialert-card)

<img src="https://github.com/Nicxe/home-assistant-smhialert-card/blob/main/Screenshot.png">
