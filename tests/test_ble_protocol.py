"""Тесты BLE-протокола Tion 4S. Без Home Assistant: модуль грузится по пути файла.

Запуск: python -m pytest tests/
"""
import importlib.util
import struct
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).parent.parent / "custom_components" / "tion" / "ble_protocol.py"
_spec = importlib.util.spec_from_file_location("tion_ble_protocol", _PATH)
bp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bp  # нужно dataclasses
_spec.loader.exec_module(bp)


def emu_state(request_id=7, *, power=True, sound=True, led=False, heater=True, heater_present=1,
              gate=0, target=18, fan=3, t_outdoor=-5, t_current=17, filter_time=86400 * 120,
              airflow=3600, errors=0, max_fan=6, heater_var=42):
    """Ответ состояния так, как его пакует эмулятор dentra (tests/emu_t4s.py)."""
    flags = 0
    if power:
        flags |= 1 << 0
    if sound:
        flags |= 1 << 1
    if led:
        flags |= 1 << 2
    if not heater:
        flags |= 1 << 4  # heater_mode = fanonly
    flags |= heater_present << 7
    return struct.pack(
        "<IHBbBbbbbIIIIIBB",
        request_id, flags, gate, target, fan, t_outdoor, t_current, 30, 31,
        1000, 2000, filter_time, airflow, errors, max_fan, heater_var,
    )


def test_crc_check_value():
    # Каталожное значение CRC-16/CCITT-FALSE
    assert bp.crc16_ccitt_false(b"123456789") == 0x29B1


def test_state_request_frame_bytes():
    frame = bp.build_frame(bp.FRAME_TYPE_STATE_REQ)
    assert frame[:10] == bytes.fromhex("0c003aad323201000000")
    assert len(frame) == 12
    assert bp.crc16_ccitt_false(frame) == 0


def test_frame_roundtrip():
    payload = bytes(range(30))
    frame = bp.build_frame(bp.FRAME_TYPE_STATE_SET, payload)
    frame_type, got = bp.parse_frame(frame)
    assert frame_type == bp.FRAME_TYPE_STATE_SET
    assert got == payload


def test_parse_frame_rejects_bad_crc():
    frame = bytearray(bp.build_frame(bp.FRAME_TYPE_STATE_REQ))
    frame[-1] ^= 0xFF
    with pytest.raises(bp.TionProtocolError):
        bp.parse_frame(bytes(frame))


def test_parse_frame_rejects_bad_size():
    frame = bp.build_frame(bp.FRAME_TYPE_STATE_REQ) + b"\x00"
    with pytest.raises(bp.TionProtocolError):
        bp.parse_frame(frame)


def test_split_single_packet():
    frame = bp.build_frame(bp.FRAME_TYPE_STATE_REQ)
    packets = bp.split_packets(frame)
    assert packets == [b"\x80" + frame]


def test_split_and_assemble_long_frame():
    frame = bp.build_frame(bp.FRAME_TYPE_STATE_RSP, emu_state())
    assert len(frame) == 47
    packets = bp.split_packets(frame)
    assert [p[0] for p in packets] == [0x00, 0x40, 0xC0]
    assert all(len(p) <= 20 for p in packets)
    asm = bp.PacketAssembler()
    assert asm.feed(packets[0]) is None
    assert asm.feed(packets[1]) is None
    assert asm.feed(packets[2]) == frame


def test_split_two_packets():
    frame = bp.build_frame(bp.FRAME_TYPE_STATE_SET, bytes(11))  # 23 байта
    packets = bp.split_packets(frame)
    assert [p[0] for p in packets] == [0x00, 0xC0]
    asm = bp.PacketAssembler()
    asm.feed(packets[0])
    assert asm.feed(packets[1]) == frame


def test_parse_state():
    st = bp.parse_state(emu_state())
    assert st.request_id == 7
    assert st.power and st.sound and not st.led
    assert st.heater_enabled
    assert st.heater_power_w == 1000 and st.heater_installed
    assert st.gate == bp.GATE_OUTDOOR
    assert st.target_temperature == 18
    assert st.fan_speed == 3
    assert st.outdoor_temperature == -5
    assert st.current_temperature == 17
    assert st.filter_days_left == 120
    assert st.airflow_m3 == pytest.approx(15.0)
    assert st.max_fan_speed == 6
    assert st.heater_var == 42


def test_parse_state_fanonly_no_heater_recirculation():
    st = bp.parse_state(emu_state(power=False, heater=False, heater_present=0, gate=1))
    assert not st.power
    assert not st.heater_enabled
    assert not st.heater_installed
    assert st.gate == bp.GATE_INDOOR


def test_parse_state_wrong_size():
    with pytest.raises(bp.TionProtocolError):
        bp.parse_state(emu_state()[:-1])


def test_state_set_matches_emulator_unpack():
    payload = bp.build_state_set(
        42, power=True, sound=True, led=False, heater_enabled=False,
        gate=bp.GATE_INDOOR, target_temperature=21, fan_speed=5,
    )
    # emu_t4s.Tion4sState.unpack: fmt "<IHBbBH"
    request_id, flags, gate, target, fan, filter_time = struct.unpack("<IHBbBH", payload)
    assert request_id == 42
    assert flags & 1  # power
    assert flags & 2  # sound
    assert not flags & 4  # led
    assert flags & (1 << 3)  # heater_mode = fanonly
    assert flags & (1 << 4)  # comm_source = USER
    assert not flags >> 8  # MagicAir-auto выключен
    assert (gate, target, fan, filter_time) == (1, 21, 5, 0)


def test_state_set_clamps_values():
    payload = bp.build_state_set(
        2, power=False, sound=False, led=False, heater_enabled=True,
        gate=2, target_temperature=40, fan_speed=0,
    )
    _req, flags, gate, target, fan, _ft = struct.unpack("<IHBbBH", payload)
    assert not flags & 1
    assert not flags & (1 << 3)  # нагрев включён
    assert gate == bp.GATE_OUTDOOR
    assert target == bp.TARGET_TEMP_MAX
    assert fan == 1  # скорости 0 у 4S нет


def test_parse_dev_info():
    payload = struct.pack("<BIHH16s", 1, 0x8003, 0x04C7, 0x0100, bytes(16))
    info = bp.parse_dev_info(payload)
    assert info.is_4s
    assert info.firmware == "04C7"
