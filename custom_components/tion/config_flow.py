"""Config flow для Tion — UI-конфигурация (CR-009/014)."""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_FILE_PATH
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, DEFAULT_AUTH_FNAME

_LOGGER = logging.getLogger(__name__)


async def _validate(hass, username: str, password: str, auth_fname: str) -> bool:
    """Попытаться авторизоваться. True при успехе."""

    def _try():
        from tion import TionApi
        api = TionApi(username, password, auth_fname=auth_fname)
        return bool(api.authorization)

    try:
        return await hass.async_add_executor_job(_try)
    except Exception as exc:
        _LOGGER.warning("Tion: ошибка авторизации — %s", exc)
        return False


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
            ok = await _validate(
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
            errors["base"] = "auth"

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_import(self, import_data):
        """YAML → config entry миграция (backward-compat для старого `tion:` блока)."""
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
    """Меняем scan_interval / file_path без пересоздания entry."""

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
