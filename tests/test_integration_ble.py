"""Сквозные тесты BLE-ветки: config flow, загрузка записи, сущности, сервисы climate."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("homeassistant.components.bluetooth")
pytest.importorskip("pytest_homeassistant_custom_component")
pytest.importorskip("tion")

sys.path.insert(0, str(Path(__file__).parent.parent))

from homeassistant import config_entries  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.tion import ble_breezer  # noqa: E402
from custom_components.tion.const import DOMAIN  # noqa: E402

from test_ble_breezer import ADDRESS, FakeBreezer4S, FakeClient  # noqa: E402


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def fake_ble(hass):
    device = FakeBreezer4S()

    async def _connect(_cls, _ble_device, _name, **_kw):
        return FakeClient(device)

    with patch.object(ble_breezer, "establish_connection", _connect), \
            patch.object(ble_breezer.bluetooth, "async_ble_device_from_address", return_value=object()), \
            patch("homeassistant.components.bluetooth.async_discovered_service_info", return_value=[]):
        yield device


async def test_flow_menu_then_ble_manual_pair(hass, fake_ble):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["cloud", "ble"]

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "ble"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "ble"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "aa:bb:cc:dd:ee:ff", "name": "Бризер Зал"}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "ble_pair"

    with patch("custom_components.tion.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Бризер Зал"
    assert result["data"] == {"connection": "ble", "address": ADDRESS, "name": "Бризер Зал"}
    assert result["result"].unique_id == ADDRESS


async def test_flow_rejects_bad_mac(hass, fake_ble):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "ble"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"address": "nope", "name": "x"})
    assert result["errors"] == {"address": "invalid_address"}


async def test_flow_pair_failure_shows_error(hass):
    with patch("homeassistant.components.bluetooth.async_discovered_service_info", return_value=[]), \
            patch.object(ble_breezer.bluetooth, "async_ble_device_from_address", return_value=None):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "ble"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"address": ADDRESS, "name": "x"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "ble_not_found"}


async def _setup_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="Бризер Зал",
        data={"connection": "ble", "address": ADDRESS, "name": "Бризер Зал"},
        options={"scan_interval": 60},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_entry_creates_entities(hass, fake_ble):
    entry = await _setup_entry(hass)
    assert entry.state is config_entries.ConfigEntryState.LOADED

    state = next(
        s for s in hass.states.async_all("climate") if s.attributes.get("friendly_name") == "Бризер Зал"
    )
    attrs = state.attributes
    assert state.state == "heat"
    assert attrs["fan_mode"] == "2"
    assert "auto" not in attrs["fan_modes"]
    assert attrs["swing_modes"] == ["vertical", "horizontal"]
    assert "eco" not in attrs["preset_modes"] and "away" not in attrs["preset_modes"]
    assert attrs["current_temperature"] == 16
    assert attrs["temperature"] == 18

    sensors = {s.attributes.get("friendly_name"): s.state for s in hass.states.async_all("sensor")}
    assert sensors["Бризер Зал Temperature in"] == "-3"
    assert sensors["Бризер Зал Fan state"] == "on"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_climate_services_reach_breezer(hass, fake_ble):
    device = fake_ble
    entry = await _setup_entry(hass)
    entity_id = next(s.entity_id for s in hass.states.async_all("climate"))

    await hass.services.async_call("climate", "set_fan_mode", {"entity_id": entity_id, "fan_mode": "5"}, blocking=True)
    assert device.fan == 5 and device.power
    assert hass.states.get(entity_id).attributes["fan_mode"] == "5"

    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": "fan_only"},
                                   blocking=True)
    assert not device.heater
    assert hass.states.get(entity_id).state == "fan_only"

    await hass.services.async_call("climate", "set_swing_mode", {"entity_id": entity_id, "swing_mode": "vertical"},
                                   blocking=True)
    assert device.gate == 1  # рециркуляция

    await hass.services.async_call("climate", "set_temperature", {"entity_id": entity_id, "temperature": 22},
                                   blocking=True)
    assert device.target == 22

    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": entity_id, "preset_mode": "boost"},
                                   blocking=True)
    assert (device.fan, device.gate, device.heater) == (6, 0, False)

    await hass.services.async_call("climate", "turn_off", {"entity_id": entity_id}, blocking=True)
    assert not device.power
    assert hass.states.get(entity_id).state == "off"

    await hass.services.async_call("climate", "turn_on", {"entity_id": entity_id}, blocking=True)
    assert device.power and device.fan == 6  # включается с прежней скоростью, не с 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
