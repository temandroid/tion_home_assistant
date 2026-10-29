"""Регрессия облачной ветки climate после перевода сеттеров на async (1.3.0)."""
import sys
import threading
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")
pytest.importorskip("tion")

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.tion import TionDataUpdateCoordinator  # noqa: E402
from custom_components.tion.climate import TionClimate  # noqa: E402

MAIN = threading.main_thread()


class FakeZone:
    def __init__(self, log):
        self.valid, self.mode, self.target_co2, self._log = True, "manual", 600, log

    def send(self):
        self._log.append(("zone", self.mode, threading.current_thread() is not MAIN))


class FakeCloudBreezer:
    """Как tion.Breezer: синхронный send(), есть зона MagicAir, смешанная заслонка."""

    def __init__(self):
        self.log = []
        self.zone = FakeZone(self.log)
        self.valid, self.name, self.guid = True, "Cloud", "guid-1"
        self.is_on, self.heater_installed, self.heater_enabled = True, True, False
        self.speed, self.gate, self.t_set, self.t_in, self.t_out = 2, 2, 18, 5, 17
        self.t_min, self.t_max, self.speed_min_set, self.speed_max_set = 0, 25, 1, 6
        self.filter_need_replace = False

    def send(self):
        self.log.append(("breezer", self.speed, threading.current_thread() is not MAIN))


@pytest.fixture
def entity(hass):
    coordinator = TionDataUpdateCoordinator(hass, timedelta(minutes=2))
    breezer = FakeCloudBreezer()
    ent = TionClimate(coordinator, breezer)
    ent.hass = hass
    with patch.object(TionClimate, "_pushed"):
        yield ent, breezer


async def test_cloud_capabilities_unchanged(entity):
    ent, _ = entity
    assert ent.available
    assert "auto" in ent.fan_modes
    assert ent.swing_modes == ["vertical", "horizontal", "both"]
    assert {"eco", "away"} <= set(ent.preset_modes)


async def test_manual_speed_sends_zone_then_breezer_in_executor(entity):
    ent, breezer = entity
    await ent.async_set_fan_mode("4")
    assert breezer.log == [("zone", "manual", True), ("breezer", 4, True)]


async def test_auto_and_eco_still_work(entity):
    ent, breezer = entity
    await ent.async_set_fan_mode("auto")
    assert breezer.zone.mode == "auto"
    assert breezer.log[-1][0] == "breezer"
    breezer.log.clear()
    await ent.async_set_preset_mode("eco")
    assert breezer.zone.target_co2 == 700
    assert [x[0] for x in breezer.log] == ["zone", "breezer"]
    assert ent.preset_mode == "eco"


async def test_hvac_off_and_heat(entity):
    ent, breezer = entity
    await ent.async_set_hvac_mode("off")
    assert breezer.speed == 0
    await ent.async_set_hvac_mode("heat")
    assert breezer.heater_enabled and breezer.speed == 1


async def test_off_shown_immediately_despite_stale_is_on(entity):
    """CR-T-033: облачный is_on обновится только при load() — состояние берём по скорости."""
    ent, breezer = entity
    await ent.async_set_fan_mode("off")
    assert breezer.is_on  # как у tion.Breezer до следующего опроса
    assert ent.fan_mode == "off"
    assert ent.hvac_mode == "off"


async def test_rejected_send_raises(entity):
    """CR-T-032: send() вернул False — ошибка видна, а не теряется молча."""
    from homeassistant.exceptions import HomeAssistantError

    ent, breezer = entity
    with patch.object(FakeCloudBreezer, "send", return_value=False):
        with pytest.raises(HomeAssistantError):
            await ent.async_set_swing_mode("vertical")
    await ent.coordinator.async_shutdown()  # снять таймер debounce у refresh


async def test_turn_off_leaves_auto(entity):
    """CR-T-036: turn_off в авто-режиме переводит зону в manual, иначе MagicAir включит обратно."""
    ent, breezer = entity
    breezer.zone.mode = "auto"
    await ent.async_turn_off()
    assert breezer.zone.mode == "manual"
    assert breezer.log[-1][:2] == ("breezer", 0)


async def test_manual_change_resets_preset(entity):
    """CR-T-038."""
    ent, _ = entity
    await ent.async_set_preset_mode("boost")
    assert ent.preset_mode == "boost"
    await ent.async_set_fan_mode("3")
    assert ent.preset_mode == "none"


async def test_preset_without_zone_skips_zone_send(entity):
    """CR-T-037: без MagicAir зону не шлём, авто-пресеты отклоняются."""
    ent, breezer = entity
    breezer.zone.valid = False
    await ent.async_set_preset_mode("sleep")
    assert [x[0] for x in breezer.log] == ["breezer"]
    await ent.async_set_preset_mode("eco")
    assert ent.preset_mode == "none"


async def test_coordinator_fails_when_cloud_down(hass):
    """CR-T-034: load() пакета ошибок не бросает — сбой ловим по get_data()."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    class Api:
        def get_data(self, force=False):
            return False

    coordinator = TionDataUpdateCoordinator(hass, timedelta(minutes=2), Api())
    coordinator.register(FakeCloudBreezer())
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
