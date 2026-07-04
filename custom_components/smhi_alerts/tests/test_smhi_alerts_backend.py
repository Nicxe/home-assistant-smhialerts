import asyncio
from datetime import UTC, datetime, timedelta
from time import monotonic

import pytest

from custom_components.smhi_alerts.config_flow import _build_entry_data
from custom_components.smhi_alerts.const import (
    AREAS_URL,
    CONF_INCLUDE_GEOMETRY,
    CONF_INCLUDE_MESSAGES,
    CONF_LANGUAGE,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_MESSAGE_TYPES,
    CONF_MODE,
    CONF_RADIUS_KM,
    DEFAULT_MESSAGE_TYPES,
)
from custom_components.smhi_alerts.sensor import (
    SmhiAlertCoordinator,
    SmhiWarningsApiClient,
)


def _coordinator(
    *,
    language="sv",
    district="12",
    include_messages=True,
    message_types=None,
):
    coordinator = object.__new__(SmhiAlertCoordinator)
    coordinator.language = language
    coordinator.mode = "district"
    coordinator.district = district
    coordinator.include_messages = include_messages
    coordinator.include_geometry = False
    coordinator.exclude_sea = False
    coordinator.message_types = []
    coordinator._allowed_message_tokens = set()
    coordinator.set_message_types(message_types or DEFAULT_MESSAGE_TYPES)
    return coordinator


def _warning_payload():
    return [
        {
            "id": 3122,
            "normalProbability": True,
            "event": {
                "sv": "Risk för vattenbrist",
                "en": "Risk for water shortage",
                "code": "WATER_SHORTAGE",
                "mhoClassification": {
                    "sv": "Hydrologi",
                    "en": "Hydrology",
                    "code": "HYD",
                },
            },
            "warningAreas": [
                {
                    "id": 9873,
                    "created": "2026-04-21T09:08:24.221Z",
                    "approximateStart": "2026-04-21T09:02:43.328Z",
                    "published": "2026-06-30T14:05:11.376Z",
                    "normalProbability": False,
                    "pushNotice": True,
                    "areaName": {"sv": "Skåne län", "en": "Skåne County"},
                    "warningLevel": {
                        "sv": "Meddelande",
                        "en": "Message",
                        "code": "MESSAGE",
                    },
                    "eventDescription": {
                        "sv": "Risk för vattenbrist - Grundvatten och vattendrag",
                        "en": "Risk for water shortage - Groundwater and watercourses",
                        "code": "WATERCOURSES_GROUNDWATER_MINOR_MAJOR",
                    },
                    "affectedAreas": [
                        {"id": 12, "sv": "Skåne län", "en": "Skåne County"}
                    ],
                    "descriptions": [
                        {
                            "title": {
                                "sv": "Händelsebeskrivning",
                                "en": "Description of incident",
                                "code": "INCIDENT",
                            },
                            "text": {
                                "sv": "Låga grundvattennivåer",
                                "en": "Low groundwater levels",
                            },
                        }
                    ],
                    "area": {
                        "type": "Feature",
                        "geometry": {"type": "Polygon", "coordinates": []},
                    },
                }
            ],
        }
    ]


def test_areas_url_uses_smhi_metadata_endpoint() -> None:
    assert AREAS_URL.endswith("/metadata/area.json")


def test_coordinate_entry_data_persists_latitude_and_longitude() -> None:
    data = _build_entry_data(
        {
            CONF_MODE: "coordinate",
            CONF_LANGUAGE: "sv",
            CONF_LOCATION: {"latitude": 55.61, "longitude": 13.0},
            CONF_RADIUS_KM: 25,
            CONF_INCLUDE_MESSAGES: True,
            CONF_INCLUDE_GEOMETRY: True,
            CONF_MESSAGE_TYPES: ["WATER_SHORTAGE"],
        },
        59.0,
        18.0,
    )

    assert data[CONF_LATITUDE] == 55.61
    assert data[CONF_LONGITUDE] == 13.0
    assert data[CONF_LOCATION] == {"latitude": 55.61, "longitude": 13.0}
    assert data[CONF_RADIUS_KM] == 25
    assert data[CONF_MESSAGE_TYPES] == ["WATER_SHORTAGE"]


def test_process_data_exposes_structured_smhi_fields() -> None:
    messages, notice, derived = _coordinator()._process_data(_warning_payload())

    assert derived == {
        "warnings_count": 0,
        "messages_count": 1,
        "alerts_count": 1,
        "highest_severity": "MESSAGE",
    }
    assert "Händelsebeskrivning" in notice

    message = messages[0]
    assert message["alert_id"] == 3122
    assert message["warning_area_id"] == 9873
    assert message["event_code"] == "WATER_SHORTAGE"
    assert message["mho_code"] == "HYD"
    assert message["event_description_code"] == "WATERCOURSES_GROUNDWATER_MINOR_MAJOR"
    assert message["area_name"] == "Skåne län"
    assert message["affected_areas"] == [
        {"id": "12", "name": "Skåne län", "sv": "Skåne län", "en": "Skåne County"}
    ]
    assert message["description_items"] == [
        {
            "code": "INCIDENT",
            "title": "Händelsebeskrivning",
            "text": "Låga grundvattennivåer",
            "title_sv": "Händelsebeskrivning",
            "title_en": "Description of incident",
            "text_sv": "Låga grundvattennivåer",
            "text_en": "Low groundwater levels",
        }
    ]
    assert message["end"] == "Okänt"
    assert message["end_raw"] is None
    assert message["end_local"] is None
    assert message["end_is_open_ended"] is True
    assert message["normal_probability"] is True
    assert message["warning_area_normal_probability"] is False
    assert message["push_notice"] is True
    assert message["created_local"] is not None


def test_message_filter_can_match_event_description_alias() -> None:
    coordinator = _coordinator(message_types=["FIRE"])

    assert coordinator._should_include_message(
        {"code": "OTHER"}, {"code": "FOREST_FIRE"}
    )


class _FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status = status
        self._payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status >= 400:
            raise AssertionError(f"unexpected status {self.status}")


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, headers, timeout):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_api_client_reuses_raw_payload_after_304() -> None:
    raw_payload = _warning_payload()
    client = object.__new__(SmhiWarningsApiClient)
    client.session = _FakeSession([_FakeResponse(304)])
    client._etag = 'W/"abc"'
    client._last_modified = "Sat, 04 Jul 2026 20:10:17 GMT"
    client._raw_warnings_data = raw_payload
    client._last_fetch_monotonic = monotonic() - 120
    client._lock = asyncio.Lock()

    assert await client.async_get_warnings() is raw_payload
    assert client.session.calls[0]["headers"]["If-None-Match"] == 'W/"abc"'


def test_retry_after_http_date_is_converted_to_seconds() -> None:
    client = object.__new__(SmhiWarningsApiClient)
    future = datetime.now(UTC) + timedelta(seconds=90)

    seconds = client._retry_after_seconds(future.strftime("%a, %d %b %Y %H:%M:%S GMT"))

    assert 1 <= seconds <= 90
