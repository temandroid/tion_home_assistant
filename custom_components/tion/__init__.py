"""Tion integration for Home Assistant."""
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_FILE_PATH
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DATA_API,
    DATA_COORDINATOR,
    MAGICAIR_DEVICE,
    BREEZER_DEVICE,
    CO2_PPM,           # noqa: F401 — re-export для платформ (backward-compat)
    HUM_PERCENT,       # noqa: F401
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_AUTH_FNAME,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

# Backward-compat re-exports — старый код платформ импортирует эти имена из пакета
TION_API = DATA_API
TION_COORDINATOR = DATA_COORDINATOR

# YAML-конфиг (deprecated) — импортируется в config entry.
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
        self.breezers = []   # list[Breezer]
        self.magicairs = []  # list[MagicAir]

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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """YAML-секция `tion:` — мигрируем в config entry через import flow."""
    if DOMAIN not in config:
        return True

    _LOGGER.warning(
        "Tion: YAML-конфигурация устарела. Удалите блок `tion:` из configuration.yaml — "
        "интеграция будет настраиваться через UI (Settings → Devices & Services)."
    )

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=config[DOMAIN],
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Главная точка инициализации интеграции (UI-конфиг или YAML-импорт)."""
    from datetime import timedelta
    from tion import Breezer, MagicAir

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    scan_interval_sec = entry.options.get(
        CONF_SCAN_INTERVAL,
        int(DEFAULT_SCAN_INTERVAL.total_seconds()),
    )
    scan_interval = timedelta(seconds=int(scan_interval_sec))

    file_path = entry.options.get(CONF_FILE_PATH, DEFAULT_AUTH_FNAME)
    auth_fname = (
        hass.config.path(DEFAULT_AUTH_FNAME) if file_path == DEFAULT_AUTH_FNAME else file_path
    )

    def _init_api():
        from tion import TionApi
        return TionApi(
            username,
            password,
            min_update_interval_sec=scan_interval.seconds,
            auth_fname=auth_fname,
        )

    try:
        api = await hass.async_add_executor_job(_init_api)
    except Exception as exc:
        raise ConfigEntryNotReady(f"Tion: ошибка авторизации: {exc}") from exc

    if not api.authorization:
        _LOGGER.error("Tion: не удалось авторизоваться — проверьте логин/пароль")
        return False

    devices = await hass.async_add_executor_job(api.get_devices)

    coordinator = TionDataUpdateCoordinator(hass, scan_interval)

    for device in devices:
        if not device.valid:
            _LOGGER.info("Tion: пропускаем невалидное устройство %s", device)
            continue
        if isinstance(device, Breezer):
            coordinator.breezers.append(device)
            coordinator.register(device)
            coordinator.register(getattr(device, "zone", None))
        elif isinstance(device, MagicAir):
            coordinator.magicairs.append(device)
            coordinator.register(device)
        else:
            _LOGGER.info("Tion: неподдерживаемое устройство %s", device)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_API: api,
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info(
        "Tion: загружено %d бризеров, %d MagicAir",
        len(coordinator.breezers),
        len(coordinator.magicairs),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Пересоздать entry при смене опций (scan_interval / file_path)."""
    await hass.config_entries.async_reload(entry.entry_id)
