from datetime import timedelta

DOMAIN = "smhi_alerts"
CONF_MODE = "mode"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_RADIUS_KM = "radius_km"
CONF_LOCATION = "location"
CONF_EXCLUDE_SEA = "exclude_sea"
CONF_DISTRICT = "district"
CONF_LANGUAGE = "language"
CONF_INCLUDE_MESSAGES = "include_messages"
CONF_INCLUDE_GEOMETRY = "include_geometry"
CONF_EXCLUDED_MESSAGE_TYPES = "excluded_message_types"  # legacy support
CONF_MESSAGE_TYPES = "message_types"
LANGUAGES = ["en", "sv"]
LANGUAGE_OPTIONS = {"en": "Engelska", "sv": "Svenska"}
DEFAULT_NAME = "SMHI Alerts"
DEFAULT_DISTRICT = "all"
DEFAULT_LANGUAGE = "sv"
DEFAULT_INCLUDE_MESSAGES = False
DEFAULT_INCLUDE_GEOMETRY = False
DEFAULT_EXCLUDED_MESSAGE_TYPES: list[str] = []
DEFAULT_MODE = "district"  # "district" | "coordinate"
DEFAULT_RADIUS_KM = 10
DEFAULT_EXCLUDE_SEA = False
SCAN_INTERVAL = timedelta(minutes=5)

# Static fallback; prefer dynamically fetched areas from SMHI API when available
DISTRICTS = {
    "1": "Stockholms län",
    "3": "Uppsala län",
    "4": "Södermanlands län",
    "5": "Östergötlands län",
    "6": "Jönköpings län",
    "7": "Kronobergs län",
    "8": "Kalmar län",
    "9": "Gotlands län",
    "10": "Blekinge län",
    "12": "Skåne län",
    "13": "Hallands län",
    "14": "Västra Götalands län",
    "17": "Värmlands län",
    "18": "Örebro län",
    "19": "Västmanlands län",
    "20": "Dalarnas län",
    "21": "Gävleborgs län",
    "22": "Västernorrlands län",
    "23": "Jämtlands län",
    "24": "Västerbottens län",
    "25": "Norrbottens län",
    "41": "Bottenviken",
    "42": "Norra Kvarken",
    "43": "Norra Bottenhavet",
    "44": "Södra Bottenhavet",
    "45": "Ålands hav",
    "46": "Skärgårdshavet",
    "47": "Finska viken",
    "48": "Norra Östersjön",
    "49": "Mellersta Östersjön",
    "50": "Rigabukten",
    "51": "Sydöstra Östersjön",
    "52": "Södra Östersjön",
    "53": "Sydvästra Östersjön",
    "54": "Bälten",
    "55": "Öresund",
    "56": "Kattegatt",
    "57": "Skagerrak",
    "58": "Vänern",
    "all": "Alla distrikt (Ej rekommenderat)",
}

# Severity order for derived metrics
SEVERITY_ORDER = ["NONE", "MESSAGE", "YELLOW", "ORANGE", "RED"]

# Marine area IDs (sea districts) as per SMHI areas
MARINE_AREA_IDS = {
    "41", "42", "43", "44", "45", "46", "47", "48", "49", "50",
    "51", "52", "53", "54", "55", "56", "57"
}

# Event codes that are explicitly marine
MARINE_EVENT_CODES = {"HIGH_SEALEVEL"}

# API endpoints
WARNINGS_URL = (
    "https://opendata-download-warnings.smhi.se/ibww/api/version/1/warning.json"
)
AREAS_URL = (
    "https://opendata-download-warnings.smhi.se/ibww/api/version/1/areas.json"
)

MESSAGE_EVENT_CATEGORIES = [
    {"value": "THUNDER", "label_sv": "Åska", "label_en": "Thunderstorm", "mho_code": "MET", "aliases": ["THUNDERSTORM"]},
    {"value": "WIND", "label_sv": "Vind", "label_en": "Wind", "mho_code": "MET", "aliases": []},
    {"value": "WIND_MOUNTAINS", "label_sv": "Vind i fjäll", "label_en": "Wind in the alpine region", "mho_code": "MET", "aliases": []},
    {"value": "WIND_MOUNTAINS_SNOW", "label_sv": "Vind och snö i fjäll", "label_en": "Wind and snow in the alpine region", "mho_code": "MET", "aliases": []},
    {"value": "STRONG_COOLING", "label_sv": "Kraftig avkylning", "label_en": "Strong cooling", "mho_code": "MET", "aliases": []},
    {"value": "SNOW", "label_sv": "Snö", "label_en": "Snow", "mho_code": "MET", "aliases": []},
    {"value": "WIND_SNOW", "label_sv": "Vind och snö", "label_en": "Wind and snow", "mho_code": "MET", "aliases": []},
    {"value": "BLACK_ICE", "label_sv": "Svartis", "label_en": "Black ice", "mho_code": "MET", "aliases": []},
    {"value": "RAIN", "label_sv": "Regn", "label_en": "Rain", "mho_code": "MET", "aliases": []},
    {"value": "FIRE", "label_sv": "Brandrisk", "label_en": "Fire risk", "mho_code": "MET", "aliases": ["FIRE RISK", "FIRE_RISK"]},
    {"value": "HIGH_TEMPERATURES", "label_sv": "Höga temperaturer", "label_en": "High temperatures", "mho_code": "MET", "aliases": ["HEAT", "HEAT WAVE", "HEATWAVE"]},
    {"value": "WIND_SEA", "label_sv": "Vind till havs", "label_en": "Wind at sea", "mho_code": "MET", "aliases": ["WIND_AT_SEA"]},
    {"value": "ICE_ACCRETION", "label_sv": "Isbildning", "label_en": "Ice accretion", "mho_code": "OCE", "aliases": []},
    {"value": "LOW_SEA_LEVEL", "label_sv": "Lågt vattenstånd", "label_en": "Low sea level", "mho_code": "OCE", "aliases": []},
    {"value": "HIGH_SEALEVEL", "label_sv": "Högt vattenstånd", "label_en": "High sea level", "mho_code": "OCE", "aliases": ["HIGH_SEA_LEVEL"]},
    {"value": "WATER_SHORTAGE", "label_sv": "Vattenbrist", "label_en": "Risk for water shortage", "mho_code": "HYD", "aliases": ["WATER SHORTAGE"]},
    {"value": "HIGH_FLOW", "label_sv": "Hög vattenföring", "label_en": "High water discharge", "mho_code": "HYD", "aliases": ["HIGH WATER DISCHARGE"]},
    {"value": "FLOODING", "label_sv": "Översvämning", "label_en": "Flooding", "mho_code": "HYD", "aliases": []},
]

MESSAGE_EVENT_DEFINITIONS = {item["value"]: item for item in MESSAGE_EVENT_CATEGORIES}
DEFAULT_MESSAGE_TYPES = [item["value"] for item in MESSAGE_EVENT_CATEGORIES]
