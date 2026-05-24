"""Константы интеграции Tion."""
from datetime import timedelta

DOMAIN = "tion"

# Ключи в hass.data[DOMAIN][entry_id]
DATA_API = "api"
DATA_COORDINATOR = "coordinator"

# Тип устройств
MAGICAIR_DEVICE = "magicair"
BREEZER_DEVICE = "breezer"

# Единицы
CO2_PPM = "ppm"
HUM_PERCENT = "%"

# Дефолты
DEFAULT_SCAN_INTERVAL = timedelta(minutes=2)
DEFAULT_AUTH_FNAME = "tion_auth"

PLATFORMS = ["climate", "sensor"]
