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
    STATE_UNKNOWN,
    MAJOR_VERSION,
    MINOR_VERSION,
)
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from tion import Breezer, Zone

from .const import DOMAIN, DATA_API, DATA_COORDINATOR

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
    data = hass.data[DOMAIN][entry.entry_id]
    api = data[DATA_API]
    coordinator = data[DATA_COORDINATOR]

    entities = []
    for breezer in coordinator.breezers:
        zones = await hass.async_add_executor_job(api.get_zones, breezer.zone.guid)
        if not zones:
            raise PlatformNotReady(f"Tion: зона для {breezer.guid} не найдена")
        zone = zones[0]
        coordinator.register(zone)
        entities.append(TionClimate(coordinator, breezer, zone))
    async_add_entities(entities)


class TionClimate(CoordinatorEntity, ClimateEntity, RestoreEntity):
    """Tion breezer (бризер с опциональным нагревателем)."""

    if _HA_GE_2024_2:
        _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, breezer: Breezer, zone: Zone):
        super().__init__(coordinator)
        self._breezer = breezer
        self._zone = zone
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
        return self._breezer.valid and self._zone.valid

    # ---------- климат ----------

    @property
    def temperature_unit(self):
        return UnitOfTemperature.CELSIUS

    @property
    def hvac_mode(self):
        if not self._breezer.valid:
            return STATE_UNKNOWN
        if self._zone.mode == "manual" and not self._breezer.is_on:
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
        return self._breezer.t_out if self._breezer.valid else STATE_UNKNOWN

    @property
    def target_temperature(self):
        return self._breezer.t_set if self._breezer.valid else STATE_UNKNOWN

    @property
    def target_temperature_step(self):
        return 1

    @property
    def min_temp(self):
        return self._breezer.t_min if self._breezer.valid else STATE_UNKNOWN

    @property
    def max_temp(self):
        return self._breezer.t_max if self._breezer.valid else STATE_UNKNOWN

    # ---------- fan ----------

    @property
    def fan_mode(self):
        if self._zone.mode == "auto":
            return FAN_AUTO
        if not self._breezer.is_on:
            return FAN_OFF
        return str(int(self._breezer.speed))

    @property
    def fan_modes(self):
        return [FAN_OFF, FAN_AUTO, "1", "2", "3", "4", "5", "6"]

    # ---------- preset ----------

    @property
    def preset_mode(self):
        _LOGGER.debug("%s preset is %s", self._breezer.name, self.preset)
        return self.preset

    @property
    def preset_modes(self):
        return [
            PRESET_SLEEP, PRESET_ACTIVITY, PRESET_HOME, PRESET_COMFORT,
            PRESET_BOOST, PRESET_ECO, PRESET_AWAY, PRESET_NONE,
        ]

    # ---------- swing ----------

    @property
    def swing_mode(self):
        return _GATE_TO_SWING.get(self._breezer.gate, SWING_HORIZONTAL)

    @property
    def swing_modes(self):
        return [SWING_VERTICAL, SWING_HORIZONTAL, SWING_BOTH]

    # ---------- setters ----------

    def turn_on(self) -> None:
        self._breezer.speed = 1
        self._breezer.send()

    def turn_off(self) -> None:
        self._breezer.speed = 0
        self._breezer.send()

    def set_swing_mode(self, swing_mode: str) -> None:
        self._breezer.gate = _SWING_TO_GATE.get(swing_mode, 2)
        _LOGGER.info("%s: swing → %s", self._breezer.name, swing_mode)
        self._breezer.send()

    def set_temperature(self, **kwargs):
        _LOGGER.info("%s: set_temperature %s", self._breezer.name, kwargs)
        if ATTR_TEMPERATURE in kwargs:
            self._breezer.t_set = int(kwargs[ATTR_TEMPERATURE])
            self._breezer.send()
        if ATTR_HVAC_MODE in kwargs:
            self.set_hvac_mode(kwargs[ATTR_HVAC_MODE])

    def set_fan_mode(self, fan_mode):
        _LOGGER.info("%s: fan_mode → %s", self._breezer.name, fan_mode)

        if fan_mode == FAN_OFF:
            if self._breezer.zone.valid:
                self._breezer.zone.mode = "manual"
                self._breezer.zone.send()
            self._breezer.speed = 0
            self._breezer.send()
            return

        if fan_mode == FAN_AUTO:
            if not self._breezer.zone.valid:
                _LOGGER.warning("Tion: AUTO требует зону с MagicAir")
                return
            # target_co2 НЕ трогаем — управляется только через preset (см. CR-006).
            self._breezer.zone.mode = "auto"
            self._breezer.zone.send()
            self._breezer.speed_min_set = 1
            self._breezer.speed_max_set = 6
            self._breezer.heater_enabled = False
            self._breezer.send()
            return

        # ручная скорость
        try:
            new_speed = int(fan_mode)
        except (TypeError, ValueError):
            _LOGGER.warning("Tion: невалидный fan_mode %r", fan_mode)
            return

        if self._breezer.zone.valid:
            self._breezer.zone.mode = "manual"
            self._breezer.zone.send()
        self._breezer.speed = new_speed
        self._breezer.send()

    def set_preset_mode(self, preset_mode):
        """Табличное применение пресета — устраняет копипасту веток."""
        _LOGGER.info("%s: preset → %s", self._breezer.name, preset_mode)

        if preset_mode == PRESET_NONE:
            self.preset = PRESET_NONE
            return

        cfg = PRESETS.get(preset_mode)
        if cfg is None:
            _LOGGER.warning("Tion: неизвестный пресет %s", preset_mode)
            self.preset = PRESET_NONE
            return

        self._breezer.gate = cfg["gate"]
        self._breezer.heater_enabled = cfg["heater"]

        if cfg["auto"]:
            self._breezer.zone.target_co2 = cfg["target_co2"]
            self._breezer.speed_min_set = cfg["speed_min"]
            self._breezer.speed_max_set = cfg["speed_max"]
            self._breezer.zone.mode = "auto"
        else:
            self._breezer.speed = cfg["speed"]
            self._breezer.zone.mode = "manual"

        self._breezer.zone.send()
        self._breezer.send()
        self.preset = preset_mode

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info("%s: hvac → %s", self._breezer.name, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            self.set_fan_mode(FAN_OFF)
        elif hvac_mode == HVACMode.HEAT:
            self._breezer.heater_enabled = True
            if self._breezer.speed == 0:
                self._breezer.speed = 1
            self._breezer.send()
        elif hvac_mode == HVACMode.FAN_ONLY:
            self._breezer.heater_enabled = False
            if self._breezer.speed == 0:
                self._breezer.speed = 1
            self._breezer.send()

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
    def mode(self) -> str:
        return self._zone.mode if self._zone.valid else STATE_UNKNOWN

    @property
    def target_co2(self) -> str:
        return self._zone.target_co2 if self._zone.valid else STATE_UNKNOWN

    @property
    def speed(self):
        return self._breezer.speed if self._breezer.valid else STATE_UNKNOWN

    @property
    def speed_min_set(self):
        return self._breezer.speed_min_set if self._breezer.valid else STATE_UNKNOWN

    @property
    def speed_max_set(self):
        return self._breezer.speed_max_set if self._breezer.valid else STATE_UNKNOWN

    @property
    def filter_need_replace(self):
        return self._breezer.filter_need_replace if self._breezer.valid else STATE_UNKNOWN

    @property
    def t_in(self):
        return self._breezer.t_in if self._breezer.valid else STATE_UNKNOWN

    @property
    def gate(self) -> str:
        return _GATE_TO_STR.get(self._breezer.gate, STATE_UNKNOWN)

    @property
    def state_attributes(self) -> dict:
        data = super().state_attributes
        data["mode"] = self.mode
        data["target_co2"] = self.target_co2
        data["speed"] = self.speed
        data["speed_min_set"] = self.speed_min_set
        data["speed_max_set"] = self.speed_max_set
        data["filter_need_replace"] = self.filter_need_replace
        data["t_in"] = self.t_in
        data["gate"] = self.gate
        return data
