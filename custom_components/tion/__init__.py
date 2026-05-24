"""Tion integration for Home Assistant."""
import logging
from datetime import timedelta

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_FILE_PATH
from homeassistant.helpers import discovery
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

DOMAIN = "tion"
TION_API = "data_tion"
TION_COORDINATOR = "tion_coordinator"

CO2_PPM = "ppm"
HUM_PERCENT = "%"

MAGICAIR_DEVICE = "magicair"
BREEZER_DEVICE = "breezer"

_LOGGER = logging.getLogger(__name__)

DEFAULT_SCAN_INTERVAL = timedelta(minutes=1)
DEFAULT_AUTH_FNAME = "tion_auth"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.time_period,
                vol.Optional(CONF_FILE_PATH, default=DEFAULT_AUTH_FNAME): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class TionDataUpdateCoordinator(DataUpdateCoordinator):
    """Один периодический refresh для всех Tion-устройств — снимает per-entity N×HTTP."""

    def __init__(self, hass, update_interval):
        super().__init__(hass, _LOGGER, name="tion", update_interval=update_interval)
        self._loadables = {}

    def register(self, obj):
        if obj is not None:
            self._loadables[id(obj)] = obj

    async def _async_update_data(self):
        def _do():
            errors = 0
            for obj in list(self._loadables.values()):
                try:
                    obj.load()
                except Exception as exc:
                    errors += 1
                    _LOGGER.debug("Tion: load() failed for %r: %s", obj, exc)
            return errors

        errors = await self.hass.async_add_executor_job(_do)
        if errors and errors == len(self._loadables):
            raise UpdateFailed("Tion: все load() завершились ошибкой")
        return True


async def async_setup(hass, config):
    """Async setup — не блокирует event loop при авторизации и discovery."""
    conf = config[DOMAIN]
    username = conf[CONF_USERNAME]
    password = conf[CONF_PASSWORD]
    scan_interval = conf[CONF_SCAN_INTERVAL]
    auth_fname = (
        hass.config.path(DEFAULT_AUTH_FNAME)
        if conf[CONF_FILE_PATH] == DEFAULT_AUTH_FNAME
        else conf[CONF_FILE_PATH]
    )

    def _init_api():
        from tion import TionApi
        return TionApi(
            username,
            password,
            min_update_interval_sec=scan_interval.seconds,
            auth_fname=auth_fname,
        )

    api = await hass.async_add_executor_job(_init_api)
    if not api.authorization:
        _LOGGER.error("Tion: не удалось получить авторизационные данные — проверьте логин/пароль")
        return False
    _LOGGER.info("Tion API initialized")

    from tion import Breezer, MagicAir

    devices = await hass.async_add_executor_job(api.get_devices)

    coordinator = TionDataUpdateCoordinator(hass, scan_interval)

    discovery_info = {}
    for device in devices:
        if not device.valid:
            _LOGGER.info("Tion: пропускаем невалидное устройство %s", device)
            continue
        if isinstance(device, Breezer):
            device_type = BREEZER_DEVICE
        elif isinstance(device, MagicAir):
            device_type = MAGICAIR_DEVICE
        else:
            _LOGGER.info("Tion: неподдерживаемое устройство %s", device)
            continue

        coordinator.register(device)
        if isinstance(device, Breezer):
            zone = getattr(device, "zone", None)
            coordinator.register(zone)
            discovery_info.setdefault("climate", []).append({"type": device_type, "guid": device.guid})
        discovery_info.setdefault("sensor", []).append({"type": device_type, "guid": device.guid})

    await coordinator.async_config_entry_first_refresh()

    hass.data[TION_API] = api
    hass.data[TION_COORDINATOR] = coordinator

    for platform, infos in discovery_info.items():
        hass.async_create_task(
            discovery.async_load_platform(hass, platform, DOMAIN, infos, config)
        )
        _LOGGER.info("Tion: найдено %d %s устройств", len(infos), platform)

    return True
