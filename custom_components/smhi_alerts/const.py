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
LANGUAGES = ["en", "sv"]
LANGUAGE_OPTIONS = {"en": "Engelska", "sv": "Svenska"}
DEFAULT_NAME = "SMHI Alerts"
DEFAULT_DISTRICT = "all"
DEFAULT_LANGUAGE = "sv"
DEFAULT_INCLUDE_MESSAGES = False
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
