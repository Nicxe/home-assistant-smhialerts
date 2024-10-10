from datetime import timedelta

DOMAIN = "smhi_alerts"
CONF_DISTRICT = "district"
CONF_LANGUAGE = "language"
CONF_INCLUDE_MESSAGES = "include_messages"  # Nytt konfigurationsalternativ
LANGUAGES = ["en", "sv"]
LANGUAGE_OPTIONS = {
    "en": "Engelska",
    "sv": "Svenska"
}
DEFAULT_NAME = "SMHI Alert"
DEFAULT_DISTRICT = "all"
DEFAULT_LANGUAGE = "sv"
DEFAULT_INCLUDE_MESSAGES = False
SCAN_INTERVAL = timedelta(minutes=5)

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
    "all": "Alla distrikt (Ej rekommenderat)"
}
