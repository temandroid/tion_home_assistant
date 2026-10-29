"""Тесты TionBleBreezer с фейковым BLE-клиентом, который отвечает как 4S.

Нужен Home Assistant (pytest-homeassistant-custom-component); без него тесты пропускаются.
На Windows HA не импортируется (fcntl) — запускать в Linux/WSL.
"""
import asyncio
import struct
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant.components.bluetooth")
pytest.importorskip("pytest_homeassistant_custom_component")

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.tion import ble_breezer  # noqa: E402
from custom_components.tion import ble_protocol as bp  # noqa: E402

ADDRESS = "AA:BB:CC:DD:EE:FF"


class FakeBreezer4S:
    """Минимальный 4S: отвечает на запрос состояния, dev_info и команду."""

    def __init__(self):
        self.power, self.heater, self.gate, self.target, self.fan = True, True, 0, 18, 2
        self.sets = []

    def state_payload(self, request_id):
        flags = (1 if self.power else 0) | (1 << 1) | (0 if self.heater else 1 << 4) | (1 << 7)
        return struct.pack("<IHBbBbbbbIIIIIBB", request_id, flags, self.gate, self.target, self.fan,
                           -3, 16, 30, 30, 1, 2, 86400 * 90, 0, 0, 6, 10)

    def handle(self, frame_type, payload):
        if frame_type == bp.FRAME_TYPE_STATE_REQ:
            return bp.FRAME_TYPE_STATE_RSP, self.state_payload(1)
        if frame_type == bp.FRAME_TYPE_DEV_INFO_REQ:
            return bp.FRAME_TYPE_DEV_INFO_RSP, struct.pack("<BIHH16s", 1, 0x8003, 0x04C7, 1, bytes(16))
        if frame_type == bp.FRAME_TYPE_STATE_SET:
            req, flags, gate, target, fan, _ft = struct.unpack("<IHBbBH", payload)
            self.sets.append((flags, gate, target, fan))
            self.power = bool(flags & 1)
            self.heater = not flags & (1 << 3)
            self.gate, self.target, self.fan = gate, target, fan
            return bp.FRAME_TYPE_STATE_RSP, self.state_payload(req)
        raise AssertionError(f"unexpected frame {frame_type:04X}")


class FakeClient:
    def __init__(self, device):
        self.device = device
        self.is_connected = True
        self.notify_cb = None
        self.asm = bp.PacketAssembler()
        self.paired = False

    async def start_notify(self, _uuid, cb):
        self.notify_cb = cb

    async def write_gatt_char(self, uuid, data, response=False):
        assert uuid == bp.CHAR_TX_UUID
        frame = self.asm.feed(bytes(data))
        if frame is None:
            return
        rsp_type, rsp = self.device.handle(*bp.parse_frame(frame))
        loop = asyncio.get_running_loop()
        for packet in bp.split_packets(bp.build_frame(rsp_type, rsp)):
            loop.call_soon(self.notify_cb, None, bytearray(packet))

    async def pair(self):
        self.paired = True

    async def disconnect(self):
        self.is_connected = False


@pytest.fixture
def fake(hass):
    device = FakeBreezer4S()
    clients = []

    async def _connect(_cls, _ble_device, _name, **_kw):
        client = FakeClient(device)
        clients.append(client)
        return client

    with patch.object(ble_breezer, "establish_connection", _connect), \
            patch.object(ble_breezer.bluetooth, "async_ble_device_from_address", return_value=object()):
        yield device, clients


async def test_load_reads_state_and_dev_info(hass, fake):
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()
    assert breezer.valid
    assert breezer.dev_info.is_4s and breezer.dev_info.firmware == "04C7"
    assert breezer.is_on and breezer.speed == 2
    assert breezer.heater_installed and breezer.heater_enabled
    assert breezer.gate == 2  # приток = «с улицы» в терминах облачной интеграции
    assert (breezer.t_in, breezer.t_out, breezer.t_set) == (-3, 16, 18)
    await breezer.async_shutdown()


async def test_send_batches_pending_changes(hass, fake):
    device, _ = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()
    breezer.speed = 5
    breezer.gate = 0  # из квартиры → рециркуляция
    breezer.heater_enabled = False
    breezer.t_set = 21
    assert breezer.speed == 5  # до отправки читаем отложенное значение
    await breezer.async_send()
    assert len(device.sets) == 1
    flags, gate, target, fan = device.sets[0]
    assert flags & 1 and flags & (1 << 3) and flags & (1 << 4)
    assert (gate, target, fan) == (bp.GATE_INDOOR, 21, 5)
    assert breezer.gate == 0 and breezer.speed == 5 and not breezer.heater_enabled
    await breezer.async_shutdown()


async def test_speed_zero_powers_off_keeping_fan(hass, fake):
    device, _ = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()
    breezer.speed = 0
    await breezer.async_send()
    flags, _gate, _target, fan = device.sets[-1]
    assert not flags & 1
    assert fan == 2
    assert not breezer.is_on and breezer.speed == 0
    await breezer.async_shutdown()


async def test_send_without_changes_is_noop(hass, fake):
    device, clients = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()
    await breezer.async_send()
    assert device.sets == []
    await breezer.async_shutdown()


async def test_reuses_connection_then_idle_disconnects(hass, fake):
    _device, clients = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()
    await breezer.async_load()
    assert len(clients) == 1
    # имитируем срабатывание таймера простоя
    breezer._cancel_idle()
    await breezer._idle_disconnect(None)
    assert not clients[0].is_connected
    await breezer.async_shutdown()


async def test_not_visible_raises(hass):
    with patch.object(ble_breezer.bluetooth, "async_ble_device_from_address", return_value=None):
        breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
        with pytest.raises(ble_breezer.TionBleError):
            await breezer.async_load()
        assert not breezer.valid
        await breezer.async_shutdown()


async def test_timeout_marks_unavailable(hass, fake):
    _device, _clients = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()

    async def _silent(*_a, **_kw):
        return None

    with patch.object(FakeClient, "write_gatt_char", _silent), \
            patch.object(ble_breezer, "RESPONSE_TIMEOUT", 0.05):
        with pytest.raises(ble_breezer.TionBleError):
            await breezer.async_load()
    assert not breezer.valid
    await breezer.async_shutdown()


async def test_pair(hass, fake):
    _device, clients = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    info = await breezer.async_pair()
    assert info.is_4s
    assert clients[0].paired
    assert all(not c.is_connected for c in clients)


async def test_setter_during_send_is_not_lost(hass, fake):
    """CR-T-035: изменение, сделанное пока ждём ответ на команду, уходит следующей командой."""
    device, _ = fake
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()

    breezer.speed = 4
    first = asyncio.ensure_future(breezer.async_send())
    await asyncio.sleep(0)  # первая команда взяла снимок и ждёт ответа
    breezer.gate = 0
    second = asyncio.ensure_future(breezer.async_send())
    await asyncio.gather(first, second)

    assert len(device.sets) == 2
    assert device.sets[-1][1] == bp.GATE_INDOOR and device.fan == 4
    assert breezer.gate == 0
    await breezer.async_shutdown()


async def test_last_speed_kept_while_off(hass, fake):
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_load()
    breezer.speed = 0
    await breezer.async_send()
    assert breezer.speed == 0 and breezer.last_speed == 2
    await breezer.async_shutdown()


async def test_no_idle_timer_after_shutdown(hass, fake):
    """CR-T-042."""
    breezer = ble_breezer.TionBleBreezer(hass, ADDRESS, "Тест")
    await breezer.async_shutdown()
    breezer._schedule_idle_disconnect()
    assert breezer._cancel_idle is None
