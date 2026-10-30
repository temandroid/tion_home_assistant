"""Облако Tion v4 (CR-T-044): координатор и адаптеры устройств для climate/sensor.

Адаптеры повторяют интерфейс облачного `tion.Breezer`/`tion.MagicAir`/`tion.Zone`
и BLE-бризера (speed/gate/heater_enabled/t_set/t_in/t_out/valid/zone…), поэтому
climate.py и sensor.py общие для всех трёх режимов. Снимок аккаунта у v4 неизменяемый
и приходит push'ем (NATS), так что адаптер хранит только id устройства и каждый раз
читает свежий `cloud.account`.
"""
from __future__ import annotations

from datetime import datetime
import logging
import time
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry, ConfigEntryState
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .cloud_v4 import (
    Breezer,
    Flap,
    Station,
    TionApiError,
    TionAuthError,
    TionAuthStaleError,
    TionCloud,
    TionCommandError,
    TionConnectionError,
    TionDeviceTimeoutError,
    TionError,
    view,
)
from .const import DOMAIN, V4_DEFAULT_TARGET_CO2, V4_DISCONNECT_GRACE, V4_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)

MODEL_NAMES = {
    "b4s_ble": "Breezer 4S",
    "br3s_rf": "Breezer 3S",
    "o2_rf": "Breezer O2",
    "bs3xx_rf": "MagicAir BS310",
    "bs4xx_rf": "MagicAir BS410",
    "thco2_rf": "Module CO2+",
}

# gate как у пакета `tion` и BLE: 0 — из квартиры, 1 — смешанный, 2 — с улицы
_FLAP_TO_GATE = {Flap.INSIDE: 0, Flap.MIXED: 1, Flap.OUTSIDE: 2}
_GATE_TO_FLAP = {v: k for k, v in _FLAP_TO_GATE.items()}

# Локально заданное значение показываем, пока облако не пришлёт его же
# (push обычно через доли секунды) — иначе UI мигал бы старым состоянием.
_PENDING_TTL = 15.0


class TionV4Error(HomeAssistantError):
    """Команда облаку v4 не прошла — текст уходит в UI."""


def _command_error(name: str, err: Exception) -> TionV4Error:
    if isinstance(err, TionDeviceTimeoutError):
        return TionV4Error(f"{name}: устройство не ответило на команду")
    if isinstance(err, TionCommandError):
        return TionV4Error(f"{name}: устройство отклонило команду: {err.message}")
    if isinstance(err, TionConnectionError):
        return TionV4Error(f"{name}: облако Tion недоступно")
    return TionV4Error(f"{name}: {err}")


class TionV4Coordinator(DataUpdateCoordinator):
    """Снимок аккаунта v4: push от TionCloud + перечитывание структуры раз в минуту."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, cloud: TionCloud) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="tion_v4",
            update_interval=V4_REFRESH_INTERVAL,
        )
        self.cloud = cloud
        self.breezers: list[TionV4Breezer] = []
        self.magicairs: list[TionV4MagicAir] = []
        # False, когда живой канал лежит дольше V4_DISCONNECT_GRACE
        self.channel_up = cloud.connected
        self._unsub_grace: CALLBACK_TYPE | None = None
        self._reauth_opened = False
        self._unsub_cloud: CALLBACK_TYPE | None = cloud.add_listener(self._handle_cloud_update)

    def build_devices(self) -> None:
        """Адаптеры для всех поддерживаемых устройств аккаунта."""
        for device in self.cloud.account.devices():
            device_view = view(device)
            if isinstance(device_view, Breezer):
                self.breezers.append(TionV4Breezer(self, device.id))
            elif isinstance(device_view, Station):
                self.magicairs.append(TionV4MagicAir(self, device.id))
            else:
                _LOGGER.info("Tion v4: неподдерживаемое устройство %s (%s)", device.name, device.product_id)

    def device_available(self, device_id: str) -> bool:
        """Канал жив, устройство и его шлюз (MagicAir) онлайн."""
        account = self.cloud.account
        if not self.channel_up or (device := account.device(device_id)) is None:
            return False
        gateway = account.device(device.parent_id) if device.parent_id is not None else None
        return device.is_online and (gateway is None or gateway.is_online)

    @callback
    def _handle_cloud_update(self) -> None:
        # Не async_set_updated_data: он перезапускает таймер, а push'и идут каждые
        # несколько секунд — периодическое перечитывание структуры не наступило бы.
        if self.cloud.connected:
            self._cancel_grace()
            self.channel_up = True
        elif self.channel_up and self._unsub_grace is None:
            self._unsub_grace = async_call_later(self.hass, V4_DISCONNECT_GRACE, self._grace_expired)
        self._sync_reauth()
        self.async_update_listeners()

    @callback
    def _grace_expired(self, _now: datetime) -> None:
        self._unsub_grace = None
        self.channel_up = False
        self.async_update_listeners()

    @callback
    def _cancel_grace(self) -> None:
        if self._unsub_grace is not None:
            self._unsub_grace()
            self._unsub_grace = None

    @callback
    def _sync_reauth(self) -> None:
        """Запрос входа, пока Tion не продлевает сессию; снять, когда продлил.

        Отказ сервера (TionAuthError) и «час без продления» (TionAuthStaleError,
        скорее сбой Tion) одинаково просят войти; второй снимается сам."""
        if self.cloud.auth_error is not None:
            # Push со старым auth_error во время reload открыл бы поток, переживший reload
            self.async_request_reauth()
        elif self._reauth_opened:
            self._reauth_opened = False
            for flow in self.hass.config_entries.flow.async_progress_by_handler(
                DOMAIN,
                match_context={"entry_id": self.config_entry.entry_id, "source": SOURCE_REAUTH},
            ):
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

    @callback
    def async_request_reauth(self) -> None:
        if not self._reauth_opened and self.config_entry.state is not ConfigEntryState.UNLOAD_IN_PROGRESS:
            self._reauth_opened = True
            self.config_entry.async_start_reauth(self.hass)

    async def _async_update_data(self):
        """Перечитать структуру (online-флаги).

        Сбой периодического перечитывания — не повод гасить сущности: состояние идёт
        push'ем, а доступность уже учитывает живой канал (channel_up) и online-флаги.
        Поэтому UpdateFailed здесь не бросаем — иначе один сбой GetStructure при живом
        NATS делал бы недоступным всё на минуту (как и у апстрима)."""
        try:
            await self.cloud.async_refresh()
        except TionAuthStaleError as err:
            _LOGGER.warning("Tion v4: облако больше часа не продлевает сессию: %s", err)
        except TionAuthError as err:
            self._reauth_opened = True  # снимется в _sync_reauth, если сессия оживёт
            raise ConfigEntryAuthFailed("Tion отклонил сохранённую сессию") from err
        except TionConnectionError as err:
            _LOGGER.debug("Tion v4: облако недоступно при перечитывании структуры: %s", err)
        except TionApiError as err:
            _LOGGER.warning("Tion v4: ошибка облака при перечитывании структуры: %s", err)
        self._sync_reauth()
        return self.cloud.account

    async def async_shutdown(self) -> None:
        # Вызывается дважды: нашим async_on_unload и самим HA для координатора с config_entry
        if self._unsub_cloud is not None:
            self._unsub_cloud()
            self._unsub_cloud = None
        self._cancel_grace()
        await super().async_shutdown()


class _TionV4Device:
    """Общее для адаптеров: id, имя, MAC, модель, доступность."""

    def __init__(self, coordinator: TionV4Coordinator, device_id: str) -> None:
        self._coordinator = coordinator
        self._id = device_id
        self._pending: dict[str, tuple[Any, float]] = {}

    @property
    def _device(self):
        return self._coordinator.cloud.account.device(self._id)

    @property
    def _view(self):
        device = self._device
        return view(device) if device is not None else None

    @property
    def guid(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        device = self._device
        return device.name if device is not None else self._id

    @property
    def macs(self) -> tuple[str, ...]:
        device = self._device
        return device.macs if device is not None else ()

    @property
    def model_name(self) -> str | None:
        device = self._device
        return MODEL_NAMES.get(device.product_id) if device is not None else None

    @property
    def firmware(self) -> str | None:
        device = self._device
        return f"{device.firmware:04X}" if device is not None and device.firmware else None

    @property
    def valid(self) -> bool:
        return self._view is not None and self._coordinator.device_available(self._id)

    def _value(self, name: str, live: Any) -> Any:
        """Локально заданное значение, пока облако не подтвердило его или не истёк TTL."""
        if name in self._pending:
            value, at = self._pending[name]
            if live == value or time.monotonic() - at > _PENDING_TTL:
                del self._pending[name]
            else:
                return value
        return live

    def _set(self, name: str, value: Any) -> None:
        self._pending[name] = (value, time.monotonic())


class TionV4MagicAir(_TionV4Device):
    """MagicAir BS310/BS410 или Module CO2+ — как tion.MagicAir для sensor.py."""

    def _station(self) -> Station | None:
        station = self._view
        return station if isinstance(station, Station) else None

    @property
    def co2(self):
        return station.co2 if (station := self._station()) else None

    @property
    def temperature(self):
        return station.temperature if (station := self._station()) else None

    @property
    def humidity(self):
        return station.humidity if (station := self._station()) else None


class TionV4Zone:
    """Авторежим комнаты бризера — как tion.Zone (mode/target_co2/valid + send)."""

    def __init__(self, breezer: TionV4Breezer) -> None:
        self._breezer = breezer

    @property
    def valid(self) -> bool:
        return self._breezer.supports_auto and self._breezer.room is not None

    @property
    def mode(self) -> str:
        auto = self._breezer.room_auto
        live = "auto" if auto is not None and auto.enabled else "manual"
        return self._breezer._value("zone_mode", live)

    @mode.setter
    def mode(self, value: str) -> None:
        self._breezer._set("zone_mode", value)

    @property
    def target_co2(self):
        auto = self._breezer.room_auto
        return self._breezer._value("target_co2", auto.co2_target if auto is not None else None)

    @target_co2.setter
    def target_co2(self, value: int) -> None:
        self._breezer._set("target_co2", value)

    async def async_send(self) -> None:
        """Только реально изменённые поля: climate шлёт зону перед каждой ручной командой."""
        pending = self._breezer._pending
        auto = self._breezer.room_auto
        changes = {}
        if "zone_mode" in pending:
            enabled = pending["zone_mode"][0] == "auto"
            # Ненастроенный авторежим — выключен: ручная команда не должна писать
            # в комнату (и падать из-за неё), ревью 1.4.0 H2
            if (auto.enabled if auto is not None else False) != enabled:
                changes["enabled"] = enabled
        if "target_co2" in pending:
            co2 = pending["target_co2"][0]
            if auto is None or auto.co2_target != co2:
                changes["co2_target"] = co2
        await self._breezer._async_set_auto(changes, forget=("zone_mode", "target_co2"))


class TionV4Breezer(_TionV4Device):
    """Бризер 4S/3S/O2 облака v4 — как tion.Breezer для climate.py/sensor.py."""

    def __init__(self, coordinator: TionV4Coordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self.zone = TionV4Zone(self)

    def _breezer(self) -> Breezer | None:
        breezer = self._view
        return breezer if isinstance(breezer, Breezer) else None

    # ---------- комната / авторежим ----------

    @property
    def room(self):
        device = self._device
        return self._coordinator.cloud.account.room_of(device) if device is not None else None

    @property
    def room_auto(self):
        room = self.room
        return room.configured_auto if room is not None else None

    @property
    def supports_auto(self) -> bool:
        """Авторежим по CO2 — когда в комнате бризера есть MagicAir или модуль CO2+."""
        device = self._device
        if device is None or device.room_id is None:
            return False
        return any(
            other.room_id == device.room_id and isinstance(view(other), Station)
            for other in self._coordinator.cloud.account.devices()
        )

    # ---------- состояние ----------

    @property
    def is_on(self) -> bool | None:
        return b.is_on if (b := self._breezer()) else None

    @property
    def speed(self):
        b = self._breezer()
        if b is None:
            return None
        live = 0 if b.is_on is False else b.speed
        return self._value("speed", live)

    @speed.setter
    def speed(self, value: int) -> None:
        self._set("speed", int(value))

    @property
    def last_speed(self):
        """Скорость для включения: облако хранит уровень и у выключенного бризера."""
        b = self._breezer()
        return b.speed if b is not None and b.speed else None

    @property
    def speed_max(self):
        return b.speed_max if (b := self._breezer()) else None

    @property
    def gate(self):
        b = self._breezer()
        live = _FLAP_TO_GATE.get(b.flap) if b is not None and b.flap is not None else None
        return self._value("gate", live)

    @gate.setter
    def gate(self, value: int) -> None:
        self._set("gate", value)

    @property
    def supports_mixed_gate(self) -> bool:
        b = self._breezer()
        return b is not None and Flap.MIXED in b.flap_modes

    @property
    def heater_installed(self) -> bool:
        b = self._breezer()
        return bool(b is not None and b.heater_installed and b.can_set("heater_enabled"))

    @property
    def heater_enabled(self):
        b = self._breezer()
        return self._value("heater_enabled", b.heater_enabled if b is not None else None)

    @heater_enabled.setter
    def heater_enabled(self, value: bool) -> None:
        self._set("heater_enabled", bool(value))

    @property
    def t_set(self):
        b = self._breezer()
        return self._value("t_set", b.target_temperature if b is not None else None)

    @t_set.setter
    def t_set(self, value) -> None:
        self._set("t_set", value)

    @property
    def t_min(self):
        b = self._breezer()
        return b.target_temperature_range[0] if b is not None else None

    @property
    def t_max(self):
        b = self._breezer()
        return b.target_temperature_range[1] if b is not None else None

    @property
    def t_in(self):
        """Воздух с улицы (на входе) — как t_in у пакета `tion` и BLE."""
        return b.temperature_outdoor if (b := self._breezer()) else None

    @property
    def t_out(self):
        """Воздух на выходе бризера."""
        return b.temperature_outlet if (b := self._breezer()) else None

    @property
    def filter_need_replace(self):
        return b.filter_needs_replacement if (b := self._breezer()) else None

    # У v4 пределы скорости авторежима — свойство комнаты, а не бризера
    @property
    def speed_min_set(self):
        auto = self.room_auto
        return self._value("speed_min_set", auto.speed_min if auto is not None else None)

    @speed_min_set.setter
    def speed_min_set(self, value: int) -> None:
        self._set("speed_min_set", int(value))

    @property
    def speed_max_set(self):
        auto = self.room_auto
        return self._value("speed_max_set", auto.speed_max if auto is not None else None)

    @speed_max_set.setter
    def speed_max_set(self, value: int) -> None:
        self._set("speed_max_set", int(value))

    # ---------- команды ----------

    def _forget(self, *names: str) -> None:
        for name in names:
            self._pending.pop(name, None)

    def _prune(self) -> None:
        """Убрать отложенные значения старше TTL — иначе они ушли бы со следующей командой."""
        now = time.monotonic()
        for name in [n for n, (_, at) in self._pending.items() if now - at > _PENDING_TTL]:
            del self._pending[name]

    async def async_send(self) -> None:
        """Отправить накопленные изменения: datapoints бризеру, пределы — комнате."""
        b = self._breezer()
        if b is None:
            raise TionV4Error(f"{self.name}: бризер не найден в аккаунте Tion")
        self._prune()
        pending = {name: value for name, (value, _) in self._pending.items()}
        changes: dict[str, Any] = {}
        if "speed" in pending:
            speed = pending["speed"]
            if speed <= 0:
                changes["is_on"] = False
            else:
                changes["is_on"] = True
                if speed != b.speed:
                    changes["speed"] = speed
        if "gate" in pending and (flap := _GATE_TO_FLAP.get(pending["gate"])) != b.flap:
            changes["flap"] = flap
        if "heater_enabled" in pending and b.can_set("heater_enabled"):
            if pending["heater_enabled"] != b.heater_enabled:
                changes["heater_enabled"] = pending["heater_enabled"]
        if "t_set" in pending and b.can_set("target_temperature"):
            if pending["t_set"] != b.target_temperature:
                changes["target_temperature"] = pending["t_set"]

        names = ("speed", "gate", "heater_enabled", "t_set")
        if changes:
            try:
                await self._coordinator.cloud.async_command(b.command(**changes))
            except (TionError, ValueError) as err:
                # и пределы: climate выставил их до этой команды, но они не ушли
                self._forget(*names, "speed_min_set", "speed_max_set")
                raise self._failed(err) from err
        # Принятые значения остаются в _pending до push'а с ними же (см. _value)
        auto = self.room_auto
        top = self.speed_max
        limits = {}
        for name, field in (("speed_min_set", "speed_min"), ("speed_max_set", "speed_max")):
            if name not in pending:
                continue
            # пределы climate рассчитаны на 6 скоростей, у O2 их 4
            value = min(pending[name], top) if top else pending[name]
            if auto is None or getattr(auto, field) != value:
                limits[field] = value
        if limits:
            await self._async_set_auto(limits, forget=("speed_min_set", "speed_max_set"))

    async def _async_set_auto(self, changes: dict[str, Any], *, forget: tuple[str, ...]) -> None:
        """Изменить авторежим комнаты; ненастроенный в облаке получает все поля."""
        if not changes:
            return
        room = self.room
        if room is None:
            self._forget(*forget)
            raise TionV4Error(f"{self.name}: бризер не в комнате — авторежим недоступен")
        if room.configured_auto is None:
            top = self.speed_max or 6
            changes = {
                "enabled": False,
                "speed_min": 1,
                "speed_max": top,
                "co2_target": V4_DEFAULT_TARGET_CO2,
                **changes,
            }
        try:
            await self._coordinator.cloud.async_set_auto_control(room.id, **changes)
        except (TionError, ValueError) as err:
            self._forget(*forget)
            raise self._failed(err) from err

    def _failed(self, err: Exception) -> TionV4Error:
        """Ошибка команды для UI; отказ авторизации заодно открывает запрос входа."""
        if isinstance(err, TionAuthError):
            self._coordinator.async_request_reauth()
        return _command_error(self.name, err)
