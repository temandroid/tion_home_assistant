"""BLE-протокол Tion 4S — кадры, CRC, разбор состояния. Без зависимостей от HA.

Формат взят из dentra/esphome-tion (components/tion-api: tion-api-ble-lt.cpp,
tion-api-4s-internal.h) и сверен с его эмулятором tests/emu_t4s.py.

Кадр (little-endian, кроме CRC):
    size:u16  magic:u8=0x3A  random:u8=0xAD  type:u16  ble_request_id:u32=1  data  crc:u16(BE)
CRC16-CCITT-FALSE (init 0xFFFF) по всему кадру без CRC; CRC по кадру вместе с CRC = 0.

Кадр режется на BLE-пакеты по 20 байт: первый байт пакета — тип
(0x00 первый, 0x40 средний, 0xC0 последний, 0x80 единственный), дальше 19 байт кадра.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SERVICE_UUID = "98f00001-3788-83ea-453e-f52244709ddb"
CHAR_TX_UUID = "98f00002-3788-83ea-453e-f52244709ddb"  # пишем сюда
CHAR_RX_UUID = "98f00003-3788-83ea-453e-f52244709ddb"  # уведомления отсюда

FRAME_MAGIC = 0x3A
FRAME_RANDOM = 0xAD
BLE_REQUEST_ID = 1

FRAME_TYPE_STATE_SET = 0x3230
FRAME_TYPE_STATE_RSP = 0x3231
FRAME_TYPE_STATE_REQ = 0x3232
FRAME_TYPE_DEV_INFO_REQ = 0x3332
FRAME_TYPE_DEV_INFO_RSP = 0x3331

PACKET_FIRST = 0x00
PACKET_MIDDLE = 0x40
PACKET_SINGLE = 0x80
PACKET_LAST = 0xC0
PACKET_DATA_SIZE = 19  # MTU 20 минус байт типа

DEVICE_TYPE_4S = 0x8003

GATE_OUTDOOR = 0  # приток
GATE_INDOOR = 1   # рециркуляция

TARGET_TEMP_MIN = 1
TARGET_TEMP_MAX = 25
FAN_SPEED_MAX = 6

_HEADER = struct.Struct("<HBBHI")       # size, magic, random, type, ble_request_id
_STATE = struct.Struct("<IHBbBbbbbIIIIIBB")  # request_id + tion4s_state_t (31 байт)
_STATE_SET = struct.Struct("<IBBBbBH")  # request_id + tion4s_state_set_t (7 байт)
_DEV_INFO = struct.Struct("<BIHH16s")   # tion_dev_info_t

# Байт 0-1 состояния (битовые поля tion4s_state_t)
_BIT_POWER = 1 << 0
_BIT_SOUND = 1 << 1
_BIT_LED = 1 << 2
_BIT_HEATER_ON = 1 << 3      # ТЭН сейчас греет
_BIT_HEATER_FANONLY = 1 << 4  # heater_mode: 0 — нагрев включён, 1 — только вентиляция
_BIT_FILTER = 1 << 6
_HEATER_PRESENT_SHIFT = 7     # 3 бита: 0 — нет, 1 — 1 кВт, 2 — 1,4 кВт
_BIT_MA_CONNECTED = 1 << 10
_BIT_MA_AUTO = 1 << 11

# Байт 0 команды (tion4s_state_set_t)
_SET_POWER = 1 << 0
_SET_SOUND = 1 << 1
_SET_LED = 1 << 2
_SET_HEATER_FANONLY = 1 << 3
_SET_COMM_USER = 1 << 4
_SET_FILTER_RESET = 1 << 7

_HEATER_POWER_W = {0: 0, 1: 1000, 2: 1400}


class TionProtocolError(Exception):
    """Битый кадр или неожиданный ответ бризера."""


def crc16_ccitt_false(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def build_frame(frame_type: int, payload: bytes = b"") -> bytes:
    size = _HEADER.size + len(payload) + 2
    body = _HEADER.pack(size, FRAME_MAGIC, FRAME_RANDOM, frame_type, BLE_REQUEST_ID) + payload
    return body + crc16_ccitt_false(body).to_bytes(2, "big")


def split_packets(frame: bytes) -> list[bytes]:
    chunks = [frame[i:i + PACKET_DATA_SIZE] for i in range(0, len(frame), PACKET_DATA_SIZE)]
    if len(chunks) == 1:
        return [bytes([PACKET_SINGLE]) + chunks[0]]
    packets = [bytes([PACKET_FIRST]) + chunks[0]]
    packets += [bytes([PACKET_MIDDLE]) + c for c in chunks[1:-1]]
    packets.append(bytes([PACKET_LAST]) + chunks[-1])
    return packets


def parse_frame(frame: bytes) -> tuple[int, bytes]:
    """Кадр → (type, payload). Payload — данные после ble_request_id, без CRC."""
    if len(frame) < _HEADER.size + 2:
        raise TionProtocolError(f"короткий кадр: {frame.hex()}")
    size, magic, _random, frame_type, _req = _HEADER.unpack_from(frame)
    if magic != FRAME_MAGIC:
        raise TionProtocolError(f"неверный magic 0x{magic:02X}")
    if size != len(frame):
        raise TionProtocolError(f"размер {size} != длине кадра {len(frame)}")
    if crc16_ccitt_false(frame) != 0:
        raise TionProtocolError(f"неверный CRC: {frame.hex()}")
    return frame_type, frame[_HEADER.size:-2]


class PacketAssembler:
    """Собирает кадр из BLE-уведомлений. feed() возвращает кадр, когда он готов."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, packet: bytes) -> bytes | None:
        if not packet:
            return None
        kind, data = packet[0], packet[1:]
        if kind == PACKET_SINGLE:
            self._buf.clear()
            return bytes(data)
        if kind == PACKET_FIRST:
            self._buf = bytearray(data)
            return None
        if kind == PACKET_MIDDLE:
            self._buf += data
            return None
        if kind == PACKET_LAST:
            frame = bytes(self._buf + data)
            self._buf.clear()
            return frame
        raise TionProtocolError(f"неизвестный тип пакета 0x{kind:02X}")


@dataclass
class Tion4sState:
    """Состояние 4S из FRAME_TYPE_STATE_RSP."""

    request_id: int
    power: bool
    sound: bool
    led: bool
    heater_active: bool      # ТЭН сейчас работает
    heater_enabled: bool     # режим «нагрев» (не «только вентиляция»)
    filter_warning: bool
    heater_power_w: int      # 0 — нагревателя нет
    ma_connected: bool
    ma_auto: bool
    gate: int                # GATE_OUTDOOR / GATE_INDOOR
    target_temperature: int
    fan_speed: int
    outdoor_temperature: int  # воздух на входе (с улицы)
    current_temperature: int  # воздух на выходе
    work_time: int            # с
    fan_time: int             # с
    filter_time: int          # остаток ресурса фильтра, с
    airflow_counter: int
    errors: int
    max_fan_speed: int
    heater_var: int           # мощность нагрева, %

    @property
    def heater_installed(self) -> bool:
        return self.heater_power_w > 0

    @property
    def filter_days_left(self) -> int:
        return self.filter_time // 86400

    @property
    def airflow_m3(self) -> float:
        return self.airflow_counter * 15.0 / 3600.0


def parse_state(payload: bytes) -> Tion4sState:
    if len(payload) != _STATE.size:
        raise TionProtocolError(f"размер состояния {len(payload)} != {_STATE.size}")
    (req, flags, gate, t_set, fan, t_outdoor, t_current, _pcb_ctl, _pcb_pwr,
     work_time, fan_time, filter_time, airflow, errors, max_fan, heater_var) = _STATE.unpack(payload)
    return Tion4sState(
        request_id=req,
        power=bool(flags & _BIT_POWER),
        sound=bool(flags & _BIT_SOUND),
        led=bool(flags & _BIT_LED),
        heater_active=bool(flags & _BIT_HEATER_ON),
        heater_enabled=not flags & _BIT_HEATER_FANONLY,
        filter_warning=bool(flags & _BIT_FILTER),
        heater_power_w=_HEATER_POWER_W.get((flags >> _HEATER_PRESENT_SHIFT) & 0b111, 0),
        ma_connected=bool(flags & _BIT_MA_CONNECTED),
        ma_auto=bool(flags & _BIT_MA_AUTO),
        gate=gate,
        target_temperature=t_set,
        fan_speed=fan,
        outdoor_temperature=t_outdoor,
        current_temperature=t_current,
        work_time=work_time,
        fan_time=fan_time,
        filter_time=filter_time,
        airflow_counter=airflow,
        errors=errors,
        max_fan_speed=max_fan,
        heater_var=heater_var,
    )


def build_state_set(
    request_id: int,
    *,
    power: bool,
    sound: bool,
    led: bool,
    heater_enabled: bool,
    gate: int,
    target_temperature: int,
    fan_speed: int,
    filter_reset: bool = False,
) -> bytes:
    """Payload FRAME_TYPE_STATE_SET. Ручной режим (comm_source=USER, MagicAir-auto выкл)."""
    flags = _SET_COMM_USER
    if power:
        flags |= _SET_POWER
    if sound:
        flags |= _SET_SOUND
    if led:
        flags |= _SET_LED
    if not heater_enabled:
        flags |= _SET_HEATER_FANONLY
    if filter_reset:
        flags |= _SET_FILTER_RESET
    target = max(TARGET_TEMP_MIN, min(TARGET_TEMP_MAX, int(target_temperature)))
    # скорость 0 у 4S нет: «выключено» — это power=False
    fan = max(1, min(FAN_SPEED_MAX, int(fan_speed)))
    gate = GATE_INDOOR if gate == GATE_INDOOR else GATE_OUTDOOR
    return _STATE_SET.pack(request_id, flags, 0, gate, target, fan, 0)


@dataclass
class Tion4sDevInfo:
    work_mode: int       # 1 — норма, 2 — режим обновления
    device_type: int
    firmware_version: int
    hardware_version: int

    @property
    def is_4s(self) -> bool:
        return self.device_type == DEVICE_TYPE_4S

    @property
    def firmware(self) -> str:
        return f"{self.firmware_version:04X}"


def parse_dev_info(payload: bytes) -> Tion4sDevInfo:
    if len(payload) != _DEV_INFO.size:
        raise TionProtocolError(f"размер dev_info {len(payload)} != {_DEV_INFO.size}")
    work_mode, device_type, fw, hw, _reserved = _DEV_INFO.unpack(payload)
    return Tion4sDevInfo(work_mode, device_type, fw, hw)
