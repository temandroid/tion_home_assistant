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
# CONNECTION_CLOUD — старое облако api2.magicair (пакет `tion`), CONNECTION_CLOUD_V4 —
# новое облако Tion v4 (CR-T-044, клиент cloud_v4/ из vaproloff/tion_home_assistant).
CONF_CONNECTION = "connection"
CONNECTION_CLOUD = "cloud"
CONNECTION_CLOUD_V4 = "cloud_v4"
CONNECTION_BLE = "ble"
CONF_ADDRESS = "address"
CONF_NAME = "name"

# Дефолты
DEFAULT_SCAN_INTERVAL = timedelta(minutes=2)
DEFAULT_BLE_SCAN_INTERVAL = timedelta(seconds=60)
DEFAULT_AUTH_FNAME = "tion_auth"

# Облако v4: ключ устройства (ECDSA P-256), к которому привязана сессия, и капча
CONF_DEVICE_KEY = "device_key"
CONF_DEVICE_KEY_ID = "device_key_id"
CONF_CAPTCHA_TOKEN = "captcha_token"
CONF_CAPTCHA_BASE_URL = "captcha_base_url"
# Опция старой облачной записи: перейти на облако v4 (запускает reauth-flow)
CONF_MIGRATE_V4 = "migrate_v4"
DOCS_CAPTCHA_URL = (
    "https://github.com/vaproloff/tion_home_assistant/blob/master/docs/captcha-localhost.md"
)
# v4 присылает состояние сам (NATS), но online-флаги меняются только в структуре
# аккаунта — её перечитываем раз в минуту.
V4_REFRESH_INTERVAL = timedelta(seconds=60)
# Сколько секунд сущности остаются доступными после обрыва живого канала
V4_DISCONNECT_GRACE = 60
# Скорость и цель CO2 для авторежима комнаты, если в облаке он ещё не настраивался
V4_DEFAULT_TARGET_CO2 = 800

PLATFORMS = ["climate", "sensor"]
