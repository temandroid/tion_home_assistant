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

# Тип подключения config entry. Записи без CONF_CONNECTION — облачные (до 1.3.0).
CONF_CONNECTION = "connection"
CONNECTION_CLOUD = "cloud"
CONNECTION_BLE = "ble"
CONF_ADDRESS = "address"
CONF_NAME = "name"

# Дефолты
DEFAULT_SCAN_INTERVAL = timedelta(minutes=2)
DEFAULT_BLE_SCAN_INTERVAL = timedelta(seconds=60)
DEFAULT_AUTH_FNAME = "tion_auth"

PLATFORMS = ["climate", "sensor"]
