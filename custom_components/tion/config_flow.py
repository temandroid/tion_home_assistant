"""Config flow для Tion — UI-конфигурация (CR-009/014)."""
import logging
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_FILE_PATH
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_BLE_SCAN_INTERVAL,
    DEFAULT_AUTH_FNAME,
    CONF_CONNECTION,
    CONNECTION_CLOUD,
    CONNECTION_BLE,
    CONF_ADDRESS,
    CONF_NAME,
)

_LOGGER = logging.getLogger(__name__)

# Те же значения, что использует пакет `tion` 1.28 — для прямого probe-запроса,
# дающего понятную причину фейла авторизации (пакет молча возвращает False).
_LEGACY_TOKEN_URL = "https://api2.magicair.tion.ru/idsrv/oauth2/token"
_LEGACY_CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
_LEGACY_CLIENT_SECRET = "syRxSrT77P"

_MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def _probe_auth(username: str, password: str) -> tuple[bool, str]:
    """Прямой probe-запрос на token endpoint Tion. Возвращает (ok, reason).

    `reason` — машинно-читаемый ключ ошибки для UI:
        "ok" | "invalid_credentials" | "client_rejected" | "grant_deprecated"
        | "endpoint_gone" | "captcha" | "network" | "unknown"
    """
    import requests

    try:
        r = requests.post(
            _LEGACY_TOKEN_URL,
            data={
                "username": username,
                "password": password,
                "client_id": _LEGACY_CLIENT_ID,
                "client_secret": _LEGACY_CLIENT_SECRET,
                "grant_type": "password",
            },
            headers={"User-Agent": "MagicAir/3.0 (HomeAssistant)"},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        _LOGGER.error("Tion auth: network error: %s", e)
        return False, "network"

    # CR-T-031: тело успешного ответа содержит access_token — в лог его не пишем
    if r.status_code == 200:
        _LOGGER.info("Tion auth probe: status=200")
        return True, "ok"
    _LOGGER.info("Tion auth probe: status=%s body=%s", r.status_code, r.text[:500])
    if r.status_code in (404, 410):
        return False, "endpoint_gone"
    body_lower = r.text.lower()
    if "<html" in body_lower or "cloudflare" in body_lower or "captcha" in body_lower:
        return False, "captcha"

    try:
        err = r.json().get("error", "")
    except Exception:
        err = ""

    if err == "invalid_grant":
        return False, "invalid_credentials"
    if err in ("invalid_client", "unauthorized_client"):
        return False, "client_rejected"
    if err == "unsupported_grant_type":
        return False, "grant_deprecated"
    return False, "unknown"


async def _validate(hass, username: str, password: str, auth_fname: str) -> tuple[bool, str]:
    """Сначала probe для понятной диагностики, потом — реальная инициализация TionApi."""
    ok, reason = await hass.async_add_executor_job(_probe_auth, username, password)
    if not ok:
        return False, reason

    def _init():
        from tion import TionApi
        api = TionApi(username, password, auth_fname=auth_fname)
        return bool(api.authorization)

    try:
        if await hass.async_add_executor_job(_init):
            return True, "ok"
        return False, "unknown"
    except Exception as e:
        _LOGGER.exception("Tion auth: TionApi init failed: %s", e)
        return False, "unknown"


def _looks_like_tion(info) -> bool:
    from .ble_protocol import SERVICE_UUID

    name = (info.name or "").lower()
    return SERVICE_UUID in info.service_uuids or "breezer" in name or "tion" in name


class TionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """UI-конфигурация Tion: облако MagicAir или один бризер 4S по Bluetooth."""

    VERSION = 1

    def __init__(self):
        self._ble_address: str | None = None
        self._ble_name: str | None = None

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["cloud", "ble"])

    # ---------- Bluetooth ----------

    async def async_step_bluetooth(self, discovery_info):
        """Бризер найден по service UUID (matcher в manifest.json)."""
        await self.async_set_unique_id(discovery_info.address.upper())
        self._abort_if_unique_id_configured()
        self._ble_address = discovery_info.address.upper()
        self._ble_name = discovery_info.name or "Tion 4S"
        self.context["title_placeholders"] = {"name": self._ble_name}
        return await self.async_step_ble_pair()

    async def async_step_ble(self, user_input=None):
        """Выбор бризера из найденных HA или ввод MAC вручную."""
        from homeassistant.components import bluetooth

        errors = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            if not _MAC_RE.match(address):  # CR-T-041
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                self._ble_address = address
                self._ble_name = user_input[CONF_NAME].strip() or "Tion 4S"
                return await self.async_step_ble_pair()

        configured = self._async_current_ids()
        found = {
            info.address.upper(): f"{info.name or '?'} ({info.address}, RSSI {info.rssi})"
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
            if _looks_like_tion(info) and info.address.upper() not in configured
        }
        # CR-T-043: со списком найденных MAC всё равно можно ввести вручную
        # (vol.In не давал, если нужный бризер не попал в список)
        address_field = (
            SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=a, label=l) for a, l in found.items()],
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )
            if found
            else str
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS): address_field,
                vol.Required(CONF_NAME, default="Tion 4S"): str,
            }
        )
        return self.async_show_form(
            step_id="ble",
            data_schema=schema,
            errors=errors,
            description_placeholders={"found": str(len(found))},
        )

    async def async_step_ble_pair(self, user_input=None):
        """Сопряжение: бризер в режиме сопряжения → BLE pair → проверка, что это 4S."""
        from .ble_breezer import TionBleBreezer, TionBleError

        errors = {}
        if user_input is not None:
            breezer = TionBleBreezer(self.hass, self._ble_address, self._ble_name)
            try:
                info = await breezer.async_pair()
            except TionBleError as exc:
                _LOGGER.warning("Tion BLE: %s", exc)
                errors["base"] = "ble_not_found" if "не виден" in str(exc) else "ble_pair_failed"
            except Exception as exc:  # BleakError и ошибки протокола
                _LOGGER.warning("Tion BLE: сопряжение %s не удалось: %s", self._ble_address, exc)
                errors["base"] = "ble_pair_failed"
            else:
                if not info.is_4s:
                    errors["base"] = "ble_not_4s"
                else:
                    return self.async_create_entry(
                        title=self._ble_name,
                        data={
                            CONF_CONNECTION: CONNECTION_BLE,
                            CONF_ADDRESS: self._ble_address,
                            CONF_NAME: self._ble_name,
                        },
                        options={
                            CONF_SCAN_INTERVAL: int(DEFAULT_BLE_SCAN_INTERVAL.total_seconds()),
                        },
                    )

        return self.async_show_form(
            step_id="ble_pair",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._ble_name, "address": self._ble_address},
        )

    # ---------- облако ----------

    async def async_step_cloud(self, user_input=None):
        errors = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            auth_fname = self.hass.config.path(DEFAULT_AUTH_FNAME)
            ok, reason = await _validate(
                self.hass,
                username,
                user_input[CONF_PASSWORD],
                auth_fname,
            )
            if ok:
                return self.async_create_entry(
                    title=f"Tion ({username})",
                    data={
                        CONF_CONNECTION: CONNECTION_CLOUD,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={
                        CONF_SCAN_INTERVAL: int(DEFAULT_SCAN_INTERVAL.total_seconds()),
                        CONF_FILE_PATH: DEFAULT_AUTH_FNAME,
                    },
                )
            # маппинг reason → ключ ошибки для translations
            errors["base"] = {
                "invalid_credentials": "invalid_auth",
                "client_rejected": "client_rejected",
                "grant_deprecated": "grant_deprecated",
                "endpoint_gone": "endpoint_gone",
                "captcha": "captcha",
                "network": "cannot_connect",
            }.get(reason, "unknown")

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="cloud", data_schema=schema, errors=errors)

    async def async_step_import(self, import_data):
        username = import_data[CONF_USERNAME]
        await self.async_set_unique_id(username.lower())
        self._abort_if_unique_id_configured()

        scan_interval = import_data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        if hasattr(scan_interval, "total_seconds"):
            scan_interval = int(scan_interval.total_seconds())

        return self.async_create_entry(
            title=f"Tion ({username}) [YAML]",
            data={
                CONF_CONNECTION: CONNECTION_CLOUD,  # CR-T-040: как у записей из UI
                CONF_USERNAME: username,
                CONF_PASSWORD: import_data[CONF_PASSWORD],
            },
            options={
                CONF_SCAN_INTERVAL: int(scan_interval),
                CONF_FILE_PATH: import_data.get(CONF_FILE_PATH, DEFAULT_AUTH_FNAME),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return TionOptionsFlow(config_entry)


class TionOptionsFlow(config_entries.OptionsFlow):
    # CR-021: не присваиваем self.config_entry (в HA 2024.11+ это property базового
    # класса, явное присваивание депрекейтнуто). Храним под приватным именем.
    def __init__(self, config_entry):
        self._entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._entry.options
        if self._entry.data.get(CONF_CONNECTION) == CONNECTION_BLE:
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(
                            CONF_SCAN_INTERVAL, int(DEFAULT_BLE_SCAN_INTERVAL.total_seconds())
                        ),
                    ): vol.All(int, vol.Range(min=15, max=600)),
                }
            )
            return self.async_show_form(step_id="init", data_schema=schema)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())),
                ): vol.All(int, vol.Range(min=30, max=3600)),
                vol.Optional(
                    CONF_FILE_PATH,
                    default=opts.get(CONF_FILE_PATH, DEFAULT_AUTH_FNAME),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
