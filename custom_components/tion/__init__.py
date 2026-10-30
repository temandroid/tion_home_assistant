"""Tion integration for Home Assistant."""
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_FILE_PATH
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    DATA_API,
    DATA_COORDINATOR,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_BLE_SCAN_INTERVAL,
    DEFAULT_AUTH_FNAME,
    PLATFORMS,
    CONF_CONNECTION,
    CONNECTION_BLE,
    CONNECTION_CLOUD_V4,
    CONF_ADDRESS,
    CONF_NAME,
)

_LOGGER = logging.getLogger(__name__)

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

    def __init__(self, hass, update_interval, api=None):
        super().__init__(hass, _LOGGER, name="tion", update_interval=update_interval)
        self._api = api      # TionApi облачной записи; у BLE — None
        self._loadables = {}
        self.breezers = []   # list[Breezer]
        self.magicairs = []  # list[MagicAir]

    def register(self, obj):
        if obj is not None:
            self._loadables[id(obj)] = obj

    async def _async_update_data(self):
        # BLE-бризеры опрашиваются в event loop (async_load), облачные объекты
        # пакета `tion` — блокирующим load() в executor.
        blocking = [o for o in self._loadables.values() if not hasattr(o, "async_load")]
        native = [o for o in self._loadables.values() if hasattr(o, "async_load")]

        def _do():
            # CR-T-034: load() пакета `tion` ошибок не бросает — при недоступном облаке
            # объекты молча оставались valid со старыми данными. Один принудительный
            # запрос /location за цикл (дальше load() берут его из кэша TionApi)
            # даёт явный сигнал сбоя.
            if self._api is not None and not self._api.get_data(force=True):
                raise UpdateFailed("Tion: облако не отдало данные")
            errors = 0
            for obj in blocking:
                try:
                    obj.load()
                except Exception as exc:
                    errors += 1
                    _LOGGER.debug("Tion: load() failed for %r: %s", obj, exc)
            return errors

        errors = await self.hass.async_add_executor_job(_do) if blocking else 0
        for obj in native:
            try:
                await obj.async_load()
            except Exception as exc:
                errors += 1
                _LOGGER.debug("Tion: async_load() failed for %r: %s", obj, exc)
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
    connection = entry.data.get(CONF_CONNECTION)
    if connection == CONNECTION_BLE:
        return await _async_setup_ble_entry(hass, entry)
    if connection == CONNECTION_CLOUD_V4:
        return await _async_setup_cloud_v4_entry(hass, entry)
    return await _async_setup_cloud_entry(hass, entry)


async def _async_setup_ble_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Один бризер 4S по BLE (встроенный адаптер или ESPHome bluetooth_proxy)."""
    from datetime import timedelta
    from .ble_breezer import TionBleBreezer

    scan_interval = timedelta(
        seconds=int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_BLE_SCAN_INTERVAL.total_seconds()))
    )
    breezer = TionBleBreezer(hass, entry.data[CONF_ADDRESS], entry.data[CONF_NAME])

    coordinator = TionDataUpdateCoordinator(hass, scan_interval)
    coordinator.breezers.append(breezer)
    coordinator.register(breezer)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await breezer.async_shutdown()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_API: breezer,
        DATA_COORDINATOR: coordinator,
    }
    entry.async_on_unload(breezer.async_shutdown)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    info = breezer.dev_info
    _LOGGER.info(
        "Tion BLE: %s (%s) подключён, прошивка %s",
        breezer.name, breezer.address, info.firmware if info else "?",
    )
    return True


async def _async_setup_cloud_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Аккаунт облака Tion / MagicAir: все бризеры и MagicAir аккаунта."""
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
            min_update_interval_sec=int(scan_interval.total_seconds()),  # CR-020
            auth_fname=auth_fname,
        )

    try:
        api = await hass.async_add_executor_job(_init_api)
    except Exception as exc:
        raise ConfigEntryNotReady(f"Tion: ошибка авторизации: {exc}") from exc

    if not api.authorization:
        await _async_raise_legacy_auth_failure(hass, username, password)

    # CR-T-039: при сбое /location get_devices() молча возвращает [] — запись
    # загрузилась бы без устройств и не повторила бы попытку.
    try:
        if not await hass.async_add_executor_job(api.get_data, True):
            # с сохранённым токеном пакет логин не повторяет и молча получает 401 —
            # проверяем вход отдельно, чтобы перенесённый аккаунт дошёл до reauth
            await _async_raise_legacy_auth_failure(hass, username, password)
        devices = await hass.async_add_executor_job(api.get_devices)
    except (ConfigEntryNotReady, ConfigEntryAuthFailed):
        raise
    except Exception as exc:
        raise ConfigEntryNotReady(f"Tion: ошибка получения устройств: {exc}") from exc

    # CR-T-044: MAC в реестр устройств — по нему запись переедет на облако v4
    # с прежними entity_id (у v4 другие ID устройств). Обёртки пакета `tion` MAC
    # не хранят, он есть только в «сырых» данных /location.
    try:
        raw_devices, _ = await hass.async_add_executor_job(api._get_devices_data)
        # нулевые и общие MAC не пишем: в одной записи connections уникальны,
        # второе устройство с тем же MAC не добавилось бы
        counts: dict[str, int] = {}
        for d in raw_devices:
            if d.guid and d.mac and d.mac.strip("0:-").strip():
                counts[d.mac.upper()] = counts.get(d.mac.upper(), 0) + 1
        macs = {
            d.guid: d.mac for d in raw_devices
            if d.guid and d.mac and counts.get(d.mac.upper()) == 1
        }
    except Exception as exc:
        _LOGGER.debug("Tion: MAC устройств не получены: %s", exc)
        macs = {}
    for device in devices:
        if device.guid in macs:
            device.macs = (macs[device.guid],)

    coordinator = TionDataUpdateCoordinator(hass, scan_interval, api)

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


async def _async_raise_legacy_auth_failure(hass: HomeAssistant, username: str, password: str):
    """Старое облако не пустило: отказ входа → reauth (переход на v4), иначе — повтор.

    Пакет `tion` не различает «неверный пароль» и «нет сети»; probe из config flow
    различает. Сетевой сбой не должен открывать reauth, который ведёт только в v4."""
    from .config_flow import _probe_auth

    ok, reason = await hass.async_add_executor_job(_probe_auth, username, password)
    if not ok and reason == "invalid_credentials":
        # CR-T-044: аккаунт, перенесённый в новое приложение MagicAir, старое облако
        # не пускает — reauth-flow ведёт ко входу в облако v4.
        raise ConfigEntryAuthFailed(
            "Tion: старое облако MagicAir отклонило вход. Если аккаунт перенесён в новое "
            "приложение Tion MagicAir — войдите заново (облако v4)."
        )
    if ok:
        raise ConfigEntryNotReady("Tion: облако не отдало список устройств")
    raise ConfigEntryNotReady(f"Tion: старое облако недоступно ({reason})")


async def _async_setup_cloud_v4_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Аккаунт нового облака Tion v4 (CR-T-044): gRPC-Web + NATS, вход с капчей."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .cloud_v4 import (
        TionAuth,
        TionAuthError,
        TionCloud,
        TionConnectionError,
        TionDeviceKey,
        TionError,
        TionTokens,
        TionTransport,
    )
    from .cloud_v4.transport import create_ssl_context
    from .cloud_v4_devices import TionV4Coordinator
    from .cloud_v4_migration import async_migrate_old_ids, async_update_migration_issue
    from .const import CONF_DEVICE_KEY

    try:
        device_key = TionDeviceKey.from_pem(entry.data[CONF_DEVICE_KEY])
        tokens = TionTokens.from_dict(entry.data)
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigEntryAuthFailed("Tion: нет сохранённой сессии облака v4") from err

    ssl_context = await hass.async_add_executor_job(create_ssl_context)
    transport = TionTransport(async_get_clientsession(hass), ssl_context)
    auth = TionAuth(transport, device_key, tokens)
    cloud = TionCloud(
        transport,
        auth,
        create_task=lambda coro, name: entry.async_create_background_task(hass, coro, name),
    )

    @callback
    def _save_tokens(new_tokens) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **new_tokens.as_dict()})

    entry.async_on_unload(auth.add_update_listener(_save_tokens))

    try:
        await cloud.async_start()
    except TionAuthError as err:
        raise ConfigEntryAuthFailed("Tion отклонил сохранённую сессию") from err
    except TionConnectionError as err:
        raise ConfigEntryNotReady("Tion: облако v4 недоступно") from err
    except TionError as err:
        raise ConfigEntryNotReady(f"Tion: ошибка облака v4: {err}") from err
    # LIFO: координатор (ниже) отписывается раньше, чем остановится облако
    entry.async_on_unload(cloud.async_stop)

    account = cloud.account
    async_migrate_old_ids(hass, entry, account)
    async_update_migration_issue(hass, entry, account)

    coordinator = TionV4Coordinator(hass, entry, cloud)
    coordinator.build_devices()
    coordinator.async_set_updated_data(account)
    entry.async_on_unload(coordinator.async_shutdown)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_API: cloud,
        DATA_COORDINATOR: coordinator,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info(
        "Tion v4: загружено %d бризеров, %d MagicAir",
        len(coordinator.breezers),
        len(coordinator.magicairs),
    )
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Убрать подсказку «аккаунт не перенесён» вместе с записью."""
    from homeassistant.helpers import issue_registry as ir

    ir.async_delete_issue(hass, DOMAIN, f"account_not_migrated_{entry.entry_id}")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Пересоздать entry при смене опций (scan_interval / file_path)."""
    # Переход на v4 меняет data и опции записи, и reload делает сам reauth-flow —
    # второй reload здесь был бы лишним циклом unload/setup.
    if entry.data.get(CONF_CONNECTION) == CONNECTION_CLOUD_V4:
        return
    hass.config_entries.async_schedule_reload(entry.entry_id)
