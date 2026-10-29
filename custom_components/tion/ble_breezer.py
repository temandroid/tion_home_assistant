"""Tion 4S по BLE через стек bluetooth HA (встроенный адаптер или ESPHome-прокси).

`TionBleBreezer` повторяет интерфейс облачного `tion.Breezer` (speed, gate,
heater_enabled, t_set, t_in, t_out, valid, ...), поэтому climate/sensor работают
с ним без отдельной ветки кода. Отличие — `async_load()`/`async_send()` вместо
блокирующих `load()`/`send()`.

Соединение не постоянное: подключаемся на время опроса/команды и отключаемся
через IDLE_DISCONNECT секунд тишины — бризер держит одно BLE-подключение,
а у прокси ограничено число слотов.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .ble_protocol import (
    CHAR_RX_UUID,
    CHAR_TX_UUID,
    FRAME_TYPE_DEV_INFO_REQ,
    FRAME_TYPE_DEV_INFO_RSP,
    FRAME_TYPE_STATE_REQ,
    FRAME_TYPE_STATE_RSP,
    FRAME_TYPE_STATE_SET,
    GATE_INDOOR,
    GATE_OUTDOOR,
    TARGET_TEMP_MAX,
    TARGET_TEMP_MIN,
    PacketAssembler,
    Tion4sDevInfo,
    Tion4sState,
    TionProtocolError,
    build_frame,
    build_state_set,
    parse_dev_info,
    parse_frame,
    parse_state,
    split_packets,
)

_LOGGER = logging.getLogger(__name__)

RESPONSE_TIMEOUT = 5.0
IDLE_DISCONNECT = 15.0

# gate облачной интеграции (0 — из квартиры, 1 — смешанный, 2 — с улицы) ↔ заслонка 4S.
# Смешанного режима у 4S нет.
_GATE_FROM_4S = {GATE_OUTDOOR: 2, GATE_INDOOR: 0}


class TionBleError(Exception):
    """Бризер недоступен по BLE или не ответил."""


class _NoZone:
    """Зоны MagicAir по BLE нет: авто-режим по CO2 недоступен."""

    valid = False
    mode = "manual"
    target_co2 = None

    def send(self) -> None:
        """Нечего отправлять."""

    def load(self) -> None:
        """Нечего загружать."""


class TionBleBreezer:
    """Один бризер Tion 4S по BLE."""

    supports_auto = False
    supports_mixed_gate = False

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address.upper()
        self.name = name
        self.zone = _NoZone()
        self.state: Tion4sState | None = None
        self.dev_info: Tion4sDevInfo | None = None
        self._pending: dict[str, Any] = {}
        self._client: BleakClientWithServiceCache | None = None
        self._lock = asyncio.Lock()
        self._assembler = PacketAssembler()
        self._waiters: dict[int, asyncio.Future] = {}
        self._request_id = 1
        self._cancel_idle = None
        self._available = False
        self._closed = False

    # ---------- интерфейс tion.Breezer ----------

    @property
    def guid(self) -> str:
        return self.address

    @property
    def valid(self) -> bool:
        return self._available and self.state is not None

    @property
    def is_on(self) -> bool:
        return bool(self._get("power"))

    @property
    def speed(self) -> int:
        return self._get("fan_speed") if self._get("power") else 0

    @speed.setter
    def speed(self, value) -> None:
        value = int(value)
        if value <= 0:
            self._pending["power"] = False
        else:
            self._pending["power"] = True
            self._pending["fan_speed"] = value

    @property
    def last_speed(self) -> int | None:
        """Скорость, с которой бризер включится (4S помнит её и в выключенном состоянии)."""
        return self._get("fan_speed")

    @property
    def gate(self) -> int:
        return _GATE_FROM_4S.get(self._get("gate"), 2)

    @gate.setter
    def gate(self, value) -> None:
        self._pending["gate"] = GATE_INDOOR if int(value) == 0 else GATE_OUTDOOR

    @property
    def heater_enabled(self) -> bool:
        return bool(self._get("heater_enabled"))

    @heater_enabled.setter
    def heater_enabled(self, value) -> None:
        self._pending["heater_enabled"] = bool(value)

    @property
    def heater_installed(self) -> bool:
        return bool(self.state and self.state.heater_installed)

    @property
    def t_set(self) -> int | None:
        return self._get("target_temperature")

    @t_set.setter
    def t_set(self, value) -> None:
        self._pending["target_temperature"] = int(value)

    @property
    def t_in(self) -> int | None:
        return self.state.outdoor_temperature if self.state else None

    @property
    def t_out(self) -> int | None:
        return self.state.current_temperature if self.state else None

    t_min = TARGET_TEMP_MIN
    t_max = TARGET_TEMP_MAX
    # Пределы скорости для авто-режима MagicAir — по BLE не используются.
    speed_min_set = None
    speed_max_set = None

    @property
    def filter_need_replace(self) -> bool | None:
        return self.state.filter_warning if self.state else None

    def _get(self, key: str):
        if key in self._pending:
            return self._pending[key]
        return getattr(self.state, key) if self.state else None

    def _forget(self, sent: dict[str, Any]) -> None:
        """Убрать из _pending отправленное, не трогая изменения, сделанные во время отправки."""
        for key, value in sent.items():
            if key in self._pending and self._pending[key] == value:
                del self._pending[key]

    # ---------- обмен ----------

    async def async_load(self) -> None:
        """Опрос состояния (вызывает координатор)."""
        async with self._lock:
            try:
                await self._ensure_connected()
                if self.dev_info is None:
                    payload = await self._request(FRAME_TYPE_DEV_INFO_REQ, b"", FRAME_TYPE_DEV_INFO_RSP)
                    self.dev_info = parse_dev_info(payload)
                payload = await self._request(FRAME_TYPE_STATE_REQ, b"", FRAME_TYPE_STATE_RSP)
                self.state = parse_state(payload)
                self._available = True
            except (BleakError, TionBleError, TionProtocolError, asyncio.TimeoutError) as exc:
                self._available = False
                await self._disconnect()
                raise TionBleError(f"{self.name}: {exc}") from exc
            finally:
                self._schedule_idle_disconnect()

    async def async_send(self) -> None:
        """Отправить накопленные изменения (speed/gate/heater/t_set) одной командой."""
        if not self._pending:
            return
        if self.state is None:
            try:
                await self.async_load()
            except TionBleError:
                # иначе отложенные значения пережили бы неудачу и маскировали
                # реальное состояние после следующего успешного опроса
                self._pending.clear()
                raise
        async with self._lock:
            # CR-T-035: снимок. Сеттер, сработавший пока ждём ответа (вторая команда
            # из автоматизации), не должен потеряться при очистке после ответа.
            sent = dict(self._pending)
            if not sent:  # уже ушло вместе с предыдущей командой
                return
            self._request_id = self._request_id % 0xFFFFFFFE + 2
            payload = build_state_set(
                self._request_id,
                power=self._get("power"),
                sound=self.state.sound,
                led=self.state.led,
                heater_enabled=self._get("heater_enabled"),
                gate=self._get("gate"),
                target_temperature=self._get("target_temperature"),
                fan_speed=self._get("fan_speed"),
            )
            try:
                await self._ensure_connected()
                rsp = await self._request(FRAME_TYPE_STATE_SET, payload, FRAME_TYPE_STATE_RSP)
                self.state = parse_state(rsp)
                self._forget(sent)
                self._available = True
            except (BleakError, TionBleError, TionProtocolError, asyncio.TimeoutError) as exc:
                self._forget(sent)
                await self._disconnect()
                raise TionBleError(f"{self.name}: команда не прошла: {exc}") from exc
            finally:
                self._schedule_idle_disconnect()

    async def async_pair(self) -> Tion4sDevInfo:
        """BLE-сопряжение (бризер должен быть в режиме сопряжения) + проверка, что это 4S."""
        async with self._lock:
            try:
                device = self._ble_device()
                client = await establish_connection(
                    BleakClientWithServiceCache, device, self.name, max_attempts=3
                )
                try:
                    await client.pair()
                finally:
                    await client.disconnect()
                await self._ensure_connected()
                payload = await self._request(FRAME_TYPE_DEV_INFO_REQ, b"", FRAME_TYPE_DEV_INFO_RSP)
                self.dev_info = parse_dev_info(payload)
                return self.dev_info
            finally:
                await self._disconnect()

    async def async_shutdown(self) -> None:
        self._closed = True
        if self._cancel_idle is not None:
            self._cancel_idle()
            self._cancel_idle = None
        async with self._lock:
            await self._disconnect()

    # ---------- BLE ----------

    def _ble_device(self) -> BLEDevice:
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None:
            raise TionBleError(
                f"{self.address} не виден ни одному Bluetooth-адаптеру или прокси HA"
            )
        return device

    async def _ensure_connected(self) -> None:
        if self._client is not None and self._client.is_connected:
            return
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            self._ble_device(),
            self.name,
            disconnected_callback=self._on_disconnected,
            max_attempts=3,
        )
        self._assembler = PacketAssembler()
        await self._client.start_notify(CHAR_RX_UUID, self._on_notify)

    async def _request(self, frame_type: int, payload: bytes, expect: int) -> bytes:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters[expect] = fut
        try:
            for packet in split_packets(build_frame(frame_type, payload)):
                await self._client.write_gatt_char(CHAR_TX_UUID, packet, response=False)
            return await asyncio.wait_for(fut, RESPONSE_TIMEOUT)
        finally:
            self._waiters.pop(expect, None)

    def _on_notify(self, _char, data: bytearray) -> None:
        try:
            frame = self._assembler.feed(bytes(data))
            if frame is None:
                return
            frame_type, payload = parse_frame(frame)
        except TionProtocolError as exc:
            _LOGGER.debug("%s: отброшен пакет %s: %s", self.name, bytes(data).hex(), exc)
            return
        fut = self._waiters.get(frame_type)
        if fut is not None and not fut.done():
            fut.set_result(payload)
        else:
            _LOGGER.debug("%s: кадр 0x%04X без запроса: %s", self.name, frame_type, payload.hex())

    @callback
    def _on_disconnected(self, _client) -> None:
        _LOGGER.debug("%s: BLE отключён", self.name)
        for fut in self._waiters.values():
            if not fut.done():
                fut.set_exception(TionBleError("соединение разорвано"))

    def _schedule_idle_disconnect(self) -> None:
        if self._cancel_idle is not None:
            self._cancel_idle()
            self._cancel_idle = None
        if self._closed:  # CR-T-042: опрос, завершившийся после выгрузки, не взводит таймер
            return
        self._cancel_idle = async_call_later(self.hass, IDLE_DISCONNECT, self._idle_disconnect)

    async def _idle_disconnect(self, _now) -> None:
        self._cancel_idle = None
        if self._lock.locked():
            return
        async with self._lock:
            await self._disconnect()

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.disconnect()
            except BleakError as exc:
                _LOGGER.debug("%s: ошибка при отключении: %s", self.name, exc)
