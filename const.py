from datetime import timedelta

DOMAIN = "smhi_alerts"
CONF_DISTRICT = "district"
CONF_LANGUAGE = "language"
LANGUAGES = ["en", "sv"]
DEFAULT_NAME = "SMHI Alert"
DEFAULT_DISTRICT = "all"
DEFAULT_LANGUAGE = "en"
SCAN_INTERVAL = timedelta(minutes=5)
