"""Config flow для Tion — UI-конфигурация (CR-009/014)."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_FILE_PATH
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_AUTH_FNAME

_LOGGER = logging.getLogger(__name__)

# Те же значения, что использует пакет `tion` 1.28 — для прямого probe-запроса,
# дающего понятную причину фейла авторизации (пакет молча возвращает False).
_LEGACY_TOKEN_URL = "https://api2.magicair.tion.ru/idsrv/oauth2/token"
_LEGACY_CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
_LEGACY_CLIENT_SECRET = "syRxSrT77P"


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

    _LOGGER.info("Tion auth probe: status=%s body=%s", r.status_code, r.text[:500])

    if r.status_code == 200:
        return True, "ok"
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


class TionConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """UI-конфигурация Tion."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

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
    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options
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
