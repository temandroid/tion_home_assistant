"""Поддержка климат-устройств Tion (бризеры + нагреватель)."""
import logging

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
    FAN_OFF,
    FAN_AUTO,
    ATTR_HVAC_MODE,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_HOME,
    PRESET_ACTIVITY,
    PRESET_SLEEP,
    PRESET_BOOST,
    PRESET_NONE,
    PRESET_ECO,
    SWING_VERTICAL,
    SWING_HORIZONTAL,
    SWING_BOTH,
)
from homeassistant.const import (
    UnitOfTemperature,
    ATTR_TEMPERATURE,
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from tion import Breezer, Zone

from .ble_breezer import TionBleError
from .const import DOMAIN, DATA_COORDINATOR

_LOGGER = logging.getLogger(__name__)

_HA_GE_2024_2 = (MAJOR_VERSION, MINOR_VERSION) >= (2024, 2)

# gate ↔ swing/строка — единый источник правды
_GATE_TO_SWING = {0: SWING_VERTICAL, 1: SWING_BOTH, 2: SWING_HORIZONTAL}
_SWING_TO_GATE = {v: k for k, v in _GATE_TO_SWING.items()}
_GATE_TO_STR = {0: "inside", 1: "combined", 2: "outside"}

# Декларативная таблица пресетов — устраняет копипасту веток.
# auto=True → zone.mode="auto" + target_co2 + speed_min/max_set.
# auto=False → zone.mode="manual" + gate/speed/heater.
PRESETS = {
    PRESET_SLEEP:    {"gate": 2, "speed": 1, "heater": False, "auto": False},
    PRESET_ACTIVITY: {"gate": 2, "speed": 2, "heater": False, "auto": False},
    PRESET_BOOST:    {"gate": 2, "speed": 6, "heater": False, "auto": False},
    PRESET_HOME:     {"gate": 0, "speed": 2, "heater": False, "auto": False},
    PRESET_COMFORT:  {"gate": 1, "speed": 3, "heater": False, "auto": False},
    PRESET_AWAY:     {"gate": 2, "target_co2": 600, "speed_min": 1, "speed_max": 6, "heater": False, "auto": True},
    PRESET_ECO:      {"gate": 2, "target_co2": 700, "speed_min": 1, "speed_max": 4, "heater": False, "auto": True},
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    # CR-019: используем breezer.zone — тот же объект, что уже зарегистрирован
    # в координаторе при setup. Отдельный get_zones() создавал ВТОРОЙ инстанс
    # зоны → рассинхрон геттеров/сеттеров и двойной HTTP.
    entities = [TionClimate(coordinator, breezer) for breezer in coordinator.breezers]
    async_add_entities(entities)


class TionClimate(CoordinatorEntity, ClimateEntity, RestoreEntity):
    """Tion breezer (бризер с опциональным нагревателем)."""

    if _HA_GE_2024_2:
        _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, breezer: Breezer):
        super().__init__(coordinator)
        self._breezer = breezer
        self._zone: Zone = breezer.zone   # CR-019: единый объект зоны
        self.preset = PRESET_NONE

    async def async_added_to_hass(self):
        """Восстановить preset после рестарта HA."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.attributes.get("preset_mode"):
            self.preset = last.attributes["preset_mode"]

    # ---------- идентификация ----------

    @property
    def unique_id(self):
        return self._breezer.guid

    @property
    def name(self):
        return f"{self._breezer.name}"

    @property
    def icon(self):
        return "mdi:air-filter"

    @property
    def available(self) -> bool:
        # у BLE зоны MagicAir нет — доступность определяет только сам бризер
        zone_ok = self._zone.valid or not self._supports_auto
        # CR-T-034: учитываем и неудачный опрос координатора (облако недоступно)
        return super().available and self._breezer.valid and zone_ok

    @property
    def device_info(self) -> DeviceInfo:
        """CR-022: группировка климата и сенсоров бризера в одно устройство."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._breezer.guid)},
            name=self._breezer.name,
            manufacturer="Tion",
            model="Breezer",
        )
        address = getattr(self._breezer, "address", None)
        if address:  # BLE
            info["connections"] = {(CONNECTION_BLUETOOTH, address)}
            info["model"] = "Breezer 4S"
            dev_info = getattr(self._breezer, "dev_info", None)
            if dev_info:
                info["sw_version"] = dev_info.firmware
        return info

    @property
    def _supports_auto(self) -> bool:
        """Авто-режим по CO2 есть только у облака с зоной MagicAir."""
        return getattr(self._breezer, "supports_auto", True)

    @property
    def _is_on(self) -> bool:
        """CR-T-033: включённость по скорости. Облачный `is_on` меняется только
        в load(), а `speed` сеттеры меняют сразу — иначе после выключения до
        следующего опроса fan_mode был бы "0" (нет в fan_modes)."""
        return (self._breezer.speed or 0) > 0

    def _resume_speed(self) -> int:
        """Скорость для включения: у BLE — последняя заданная, у облака — 1."""
        return getattr(self._breezer, "last_speed", None) or 1

    # ---------- климат ----------

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self):
        # CR-023: невалидное состояние → None, не строка
        if not self._breezer.valid:
            return None
        if self._zone.mode == "manual" and not self._is_on:
            return HVACMode.OFF
        if self._breezer.heater_enabled:
            return HVACMode.HEAT
        return HVACMode.FAN_ONLY

    @property
    def hvac_modes(self):
        modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
        if self._breezer.heater_installed:
            modes.append(HVACMode.HEAT)
        return modes

    @property
    def current_temperature(self):
        return self._breezer.t_out if self._breezer.valid else None

    @property
    def target_temperature(self):
        return self._breezer.t_set if self._breezer.valid else None

    @property
    def target_temperature_step(self):
        return 1

    @property
    def min_temp(self):
        return self._breezer.t_min if self._breezer.valid else None

    @property
    def max_temp(self):
        return self._breezer.t_max if self._breezer.valid else None

    # ---------- fan ----------

    @property
    def fan_mode(self):
        if self._zone.mode == "auto":
            return FAN_AUTO
        if not self._is_on:
            return FAN_OFF
        return str(int(self._breezer.speed))

    @property
    def fan_modes(self):
        speeds = ["1", "2", "3", "4", "5", "6"]
        return [FAN_OFF, FAN_AUTO, *speeds] if self._supports_auto else [FAN_OFF, *speeds]

    # ---------- preset ----------

    @property
    def preset_mode(self):
        _LOGGER.debug("%s preset is %s", self._breezer.name, self.preset)
        return self.preset

    @property
    def preset_modes(self):
        modes = [
            PRESET_SLEEP, PRESET_ACTIVITY, PRESET_HOME, PRESET_COMFORT,
            PRESET_BOOST, PRESET_ECO, PRESET_AWAY,
        ]
        if not self._supports_auto:
            modes = [m for m in modes if not PRESETS[m]["auto"]]
        return modes + [PRESET_NONE]

    # ---------- swing ----------

    @property
    def swing_mode(self):
        return _GATE_TO_SWING.get(self._breezer.gate, SWING_HORIZONTAL)

    @property
    def swing_modes(self):
        if getattr(self._breezer, "supports_mixed_gate", True):
            return [SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH]
        return [SWING_VERTICAL, SWING_HORIZONTAL]

    # ---------- setters ----------

    async def _async_send(self, obj) -> None:
        """BLE-бризер шлёт команду сам (async_send), облачные объекты пакета
        `tion` — блокирующим send() в executor.

        CR-T-032: облачный send() об ошибке не бросает, а возвращает False —
        раньше команда терялась молча, а UI показывал уже изменённые локально поля.
        Теперь ошибка видна в UI, а состояние перечитывается из облака."""
        if hasattr(obj, "async_send"):
            try:
                await obj.async_send()
            except TionBleError as exc:
                raise HomeAssistantError(str(exc)) from exc
            return
        if await self.hass.async_add_executor_job(obj.send) is False:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(f"{self._breezer.name}: облако Tion не приняло команду")

    def _pushed(self) -> None:
        """CR-024: после отправки команды сразу перечитать состояние в HA,
        не дожидаясь периодического refresh (поля breezer/zone уже обновлены
        локально перед send)."""
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        self.preset = PRESET_NONE
        self._breezer.speed = self._resume_speed()
        await self._async_send(self._breezer)
        self._pushed()

    async def async_turn_off(self) -> None:
        # CR-T-036: как hvac OFF — зона в manual, иначе MagicAir-авто включит бризер обратно
        await self.async_set_fan_mode(FAN_OFF)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self.preset = PRESET_NONE
        self._breezer.gate = _SWING_TO_GATE.get(swing_mode, 2)
        _LOGGER.info("%s: swing → %s", self._breezer.name, swing_mode)
        await self._async_send(self._breezer)
        self._pushed()

    async def async_set_temperature(self, **kwargs):
        _LOGGER.info("%s: set_temperature %s", self._breezer.name, kwargs)
        if ATTR_TEMPERATURE in kwargs:
            self._breezer.t_set = int(kwargs[ATTR_TEMPERATURE])
            await self._async_send(self._breezer)
        if ATTR_HVAC_MODE in kwargs:
            await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])
        self._pushed()

    async def async_set_fan_mode(self, fan_mode):
        _LOGGER.info("%s: fan_mode → %s", self._breezer.name, fan_mode)
        # CR-T-038: ручное изменение — пресет больше не соответствует состоянию
        self.preset = PRESET_NONE

        if fan_mode == FAN_OFF:
            if self._zone.valid:
                self._zone.mode = "manual"
                await self._async_send(self._zone)
            self._breezer.speed = 0
            await self._async_send(self._breezer)
            self._pushed()
            return

        if fan_mode == FAN_AUTO:
            if not self._zone.valid:
                _LOGGER.warning("Tion: AUTO требует зону с MagicAir")
                return
            # target_co2 НЕ трогаем — управляется только через preset (см. CR-006).
            self._zone.mode = "auto"
            await self._async_send(self._zone)
            self._breezer.speed_min_set = 1
            self._breezer.speed_max_set = 6
            self._breezer.heater_enabled = False
            await self._async_send(self._breezer)
            self._pushed()
            return

        # ручная скорость
        try:
            new_speed = int(fan_mode)
        except (TypeError, ValueError):
            _LOGGER.warning("Tion: невалидный fan_mode %r", fan_mode)
            return

        if self._zone.valid:
            self._zone.mode = "manual"
            await self._async_send(self._zone)
        self._breezer.speed = new_speed
        await self._async_send(self._breezer)
        self._pushed()

    async def async_set_preset_mode(self, preset_mode):
        """Табличное применение пресета — устраняет копипасту веток."""
        _LOGGER.info("%s: preset → %s", self._breezer.name, preset_mode)

        if preset_mode == PRESET_NONE:
            self.preset = PRESET_NONE
            self._pushed()
            return

        cfg = PRESETS.get(preset_mode)
        if cfg is None or (cfg["auto"] and not (self._supports_auto and self._zone.valid)):
            _LOGGER.warning("Tion: пресет %s недоступен", preset_mode)
            self.preset = PRESET_NONE
            return

        self._breezer.gate = cfg["gate"]
        self._breezer.heater_enabled = cfg["heater"]

        if cfg["auto"]:
            self._zone.target_co2 = cfg["target_co2"]
            self._breezer.speed_min_set = cfg["speed_min"]
            self._breezer.speed_max_set = cfg["speed_max"]
            self._zone.mode = "auto"
        else:
            self._breezer.speed = cfg["speed"]
            self._zone.mode = "manual"

        if self._zone.valid:  # CR-T-037: без MagicAir зону не шлём (как в set_fan_mode)
            await self._async_send(self._zone)
        await self._async_send(self._breezer)
        self.preset = preset_mode
        self._pushed()

    async def async_set_hvac_mode(self, hvac_mode):
        _LOGGER.info("%s: hvac → %s", self._breezer.name, hvac_mode)
        self.preset = PRESET_NONE
        if hvac_mode == HVACMode.OFF:
            await self.async_set_fan_mode(FAN_OFF)
        elif hvac_mode in (HVACMode.HEAT, HVACMode.FAN_ONLY):
            self._breezer.heater_enabled = hvac_mode == HVACMode.HEAT
            if not self._is_on:
                self._breezer.speed = self._resume_speed()
            await self._async_send(self._breezer)
            self._pushed()

    # ---------- features ----------

    @property
    def supported_features(self):
        supports = (
            ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.SWING_MODE
        )
        if self._breezer.heater_installed:
            supports |= ClimateEntityFeature.TARGET_TEMPERATURE
        if _HA_GE_2024_2:
            supports |= ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        return supports

    # ---------- доп. атрибуты ----------

    @property
    def mode(self):
        return self._zone.mode if self._zone.valid else None

    @property
    def target_co2(self):
        return self._zone.target_co2 if self._zone.valid else None

    @property
    def speed(self):
        return self._breezer.speed if self._breezer.valid else None

    @property
    def speed_min_set(self):
        return self._breezer.speed_min_set if self._breezer.valid else None

    @property
    def speed_max_set(self):
        return self._breezer.speed_max_set if self._breezer.valid else None

    @property
    def filter_need_replace(self):
        return self._breezer.filter_need_replace if self._breezer.valid else None

    @property
    def t_in(self):
        return self._breezer.t_in if self._breezer.valid else None

    @property
    def gate(self):
        return _GATE_TO_STR.get(self._breezer.gate) if self._breezer.valid else None

    @property
    def extra_state_attributes(self) -> dict:
        """CR-025: кастомные атрибуты через extra_state_attributes, без override базового."""
        return {
            "mode": self.mode,
            "target_co2": self.target_co2,
            "speed": self.speed,
            "speed_min_set": self.speed_min_set,
            "speed_max_set": self.speed_max_set,
            "filter_need_replace": self.filter_need_replace,
            "t_in": self.t_in,
            "gate": self.gate,
        }
