"""Sensor platform: CO2/temp/humidity (MagicAir) и temp_in/out/speed/fan_state (бризер)."""
import logging

from homeassistant.components.sensor import SensorStateClass, SensorEntity
from homeassistant.components.sensor import ATTR_STATE_CLASS as STATE_CLASS
from homeassistant.const import UnitOfTemperature, STATE_UNKNOWN
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN, DATA_API, DATA_COORDINATOR,
    BREEZER_DEVICE, MAGICAIR_DEVICE,
    CO2_PPM, HUM_PERCENT,
)

_LOGGER = logging.getLogger(__name__)

# Описания сенсоров. `key` — стабильный идентификатор для unique_id (не меняется!).
CO2_SENSOR = {
    "key": "co2", "name": "co2", "unit": CO2_PPM,
    STATE_CLASS: SensorStateClass.MEASUREMENT,
}
TEMP_SENSOR = {
    "key": "temperature", "name": "temperature", "unit": UnitOfTemperature.CELSIUS,
    STATE_CLASS: SensorStateClass.MEASUREMENT,
}
HUM_SENSOR = {
    "key": "humidity", "name": "humidity", "unit": HUM_PERCENT,
    STATE_CLASS: SensorStateClass.MEASUREMENT,
}
TEMP_IN_SENSOR = {
    "key": "temperature_in", "name": "temperature in", "unit": UnitOfTemperature.CELSIUS,
    STATE_CLASS: SensorStateClass.MEASUREMENT,
}
TEMP_OUT_SENSOR = {
    "key": "temperature_out", "name": "temperature out", "unit": UnitOfTemperature.CELSIUS,
    STATE_CLASS: SensorStateClass.MEASUREMENT,
}
SPEED_SENSOR = {
    "key": "speed", "name": "speed", "unit": "",
    STATE_CLASS: SensorStateClass.MEASUREMENT,
}
FAN_STATE_SENSOR = {
    "key": "fan_state", "name": "fan state",
    STATE_CLASS: None,
}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data[DATA_COORDINATOR]

    entities = []
    for magicair in coordinator.magicairs:
        for st in (CO2_SENSOR, TEMP_SENSOR, HUM_SENSOR):
            entities.append(TionSensor(coordinator, magicair, st))
    for breezer in coordinator.breezers:
        for st in (TEMP_IN_SENSOR, TEMP_OUT_SENSOR, SPEED_SENSOR, FAN_STATE_SENSOR):
            entities.append(TionSensor(coordinator, breezer, st))
    async_add_entities(entities)


class TionSensor(CoordinatorEntity, SensorEntity):

    def __init__(self, coordinator, device, sensor_type):
        super().__init__(coordinator)
        self._device = device
        self._sensor_type = sensor_type

    @property
    def unique_id(self):
        return f"{self._device.guid}_{self._sensor_type['key']}"

    @property
    def name(self):
        return f"{self._device.name} {self._sensor_type['name']}"

    @property
    def state(self):
        if not self._device.valid:
            return STATE_UNKNOWN
        key = self._sensor_type["key"]
        if key == "co2":
            return self._device.co2
        if key == "temperature":
            return self._device.temperature
        if key == "humidity":
            return self._device.humidity
        if key == "temperature_in":
            return self._device.t_in
        if key == "temperature_out":
            return self._device.t_out
        if key == "speed":
            return self._device.speed
        if key == "fan_state":
            speed = self._device.speed or 0
            return "on" if speed > 0 else "off"
        return STATE_UNKNOWN

    @property
    def unit_of_measurement(self):
        if self._sensor_type["key"] == "fan_state":
            return None
        return self._sensor_type.get("unit") if self._device.valid else None

    @property
    def state_class(self):
        return self._sensor_type[STATE_CLASS] if self._device.valid else None

    @property
    def available(self) -> bool:
        return self._device.valid
