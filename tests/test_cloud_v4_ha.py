"""Облако v4 (CR-T-044): адаптеры, climate/sensor, config flow, переезд со старого облака."""
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")
pytest.importorskip("tion")

sys.path.insert(0, str(Path(__file__).parent.parent))

from homeassistant import config_entries  # noqa: E402
from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.helpers import device_registry as dr, entity_registry as er  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.tion.cloud_v4 import TionDeviceKey, TionDeviceTimeoutError, TionTokens  # noqa: E402
from custom_components.tion.cloud_v4.auth import TionLoginError  # noqa: E402
from custom_components.tion.const import DOMAIN  # noqa: E402

from cloud_v4.fake_cloud import (  # noqa: E402
    BEDROOM_ID,
    BREEZER_3S,
    BREEZER_4S,
    MAGICAIR,
    FakeAuth,
    FakeTionCloud,
    default_account,
)

EMAIL = "user@example.com"
DEVICE_KEY = TionDeviceKey.generate()
TOKENS = TionTokens(
    access_token="access",
    renew_session_token="renew",
    access_expires_at=4_000_000_000.0,
    refresh_expires_at=4_000_000_000.0,
)
V4_DATA = {
    "connection": "cloud_v4",
    "email": EMAIL,
    "device_key": DEVICE_KEY.to_pem(),
    "device_key_id": DEVICE_KEY.key_id(),
    **TOKENS.as_dict(),
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def cloud():
    return FakeTionCloud()


@pytest.fixture
def patched_cloud(cloud):
    with patch("custom_components.tion.cloud_v4.TionCloud", return_value=cloud), \
            patch("custom_components.tion.cloud_v4.TionAuth", return_value=FakeAuth()):
        yield cloud


async def _setup(hass, data=None, unique_id=EMAIL, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=unique_id, title=f"Tion ({EMAIL})",
        data=data or V4_DATA, options=options or {},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _climate(hass, device_id):
    return er.async_get(hass).async_get_entity_id("climate", DOMAIN, device_id)


def _calls(cloud, kind):
    return [arg for name, arg in cloud.calls if name == kind]


def _sent(cloud):
    """Последняя команда как {код datapoint: значение}."""
    account = cloud.account
    command = _calls(cloud, "command")[-1]
    profile = account.device(command.device_id).profile
    return {
        next(spec.code for spec in profile.dps if spec.dp_id == value.dp_id): value.value
        for value in command.values
    }


# ---------- загрузка и сущности ----------

async def test_setup_creates_entities(hass, patched_cloud):
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get(_climate(hass, BREEZER_4S))
    assert state.state == "heat"  # 4S в фикстуре: нагреватель есть и разрешён
    attrs = state.attributes
    assert attrs["fan_mode"] == "3"
    assert attrs["swing_mode"] == "horizontal"  # flap OUTSIDE → с улицы
    assert attrs["swing_modes"] == ["vertical", "horizontal"]  # у 4S нет смешанного
    assert attrs["current_temperature"] == 18.5
    assert attrs["temperature"] == 15.0
    assert attrs["t_in"] == -5.2
    assert "auto" in attrs["fan_modes"]  # в спальне есть MagicAir
    assert attrs["mode"] == "manual"
    assert attrs["speed_min_set"] == 1 and attrs["speed_max_set"] == 4

    co2 = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{MAGICAIR}_co2")
    assert hass.states.get(co2).state == "650"

    device = next(
        d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        if (DOMAIN, BREEZER_4S) in d.identifiers
    )
    assert device.model == "Breezer 4S"
    assert {kind for kind, _ in device.connections} == {dr.CONNECTION_NETWORK_MAC}


async def test_heat_mode_and_3s_mixed_gate(hass, patched_cloud, cloud):
    await _setup(hass)
    # 3S: выключен, есть смешанный режим; в гостиной BS310 — авто есть, хотя не настроен
    attrs = hass.states.get(_climate(hass, BREEZER_3S)).attributes
    assert hass.states.get(_climate(hass, BREEZER_3S)).state == "off"
    assert attrs["swing_modes"] == ["vertical", "horizontal", "both"]
    assert attrs["swing_mode"] == "both"  # flap_mode=2 → MIXED
    assert "auto" in attrs["fan_modes"] and attrs["mode"] == "manual"
    # O2 вне комнаты — без авто
    assert "auto" not in hass.states.get(_climate(hass, "BO20000001")).attributes["fan_modes"]


async def test_set_fan_speed_sends_command(hass, patched_cloud, cloud):
    await _setup(hass)
    entity_id = _climate(hass, BREEZER_4S)
    await hass.services.async_call("climate", "set_fan_mode", {"entity_id": entity_id, "fan_mode": "5"}, blocking=True)
    assert _sent(cloud) == {"on_off": 1, "fan_speed_level": 5}
    # зона уже manual — лишнего запроса авторежима нет
    assert _calls(cloud, "auto_control") == []
    assert hass.states.get(entity_id).attributes["fan_mode"] == "5"


async def test_turn_off_keeps_speed(hass, patched_cloud, cloud):
    await _setup(hass)
    entity_id = _climate(hass, BREEZER_4S)
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": "off"}, blocking=True)
    assert _sent(cloud) == {"on_off": 0}
    state = hass.states.get(entity_id)
    assert state.state == "off" and state.attributes["fan_mode"] == "off"

    # включение — с прежней скоростью 3, которую облако хранит
    await hass.services.async_call("climate", "turn_on", {"entity_id": entity_id}, blocking=True)
    assert _sent(cloud) == {"on_off": 1}
    assert hass.states.get(entity_id).attributes["fan_mode"] == "3"


async def test_fan_auto_enables_room_auto(hass, patched_cloud, cloud):
    await _setup(hass)
    entity_id = _climate(hass, BREEZER_4S)
    await hass.services.async_call("climate", "set_fan_mode", {"entity_id": entity_id, "fan_mode": "auto"}, blocking=True)
    assert _calls(cloud, "auto_control") == [
        (BEDROOM_ID, {"enabled": True}),
        (BEDROOM_ID, {"speed_max": 6}),  # speed_min=1 уже стоит
    ]
    assert _sent(cloud) == {"heater_on_off": 1}  # у 4S «нагрев выключен» = уровень 1
    attrs = hass.states.get(entity_id).attributes
    assert attrs["fan_mode"] == "auto" and attrs["speed_max_set"] == 6


async def test_preset_eco(hass, patched_cloud, cloud):
    await _setup(hass)
    entity_id = _climate(hass, BREEZER_4S)
    await hass.services.async_call("climate", "set_preset_mode", {"entity_id": entity_id, "preset_mode": "eco"}, blocking=True)
    assert _calls(cloud, "auto_control") == [
        (BEDROOM_ID, {"enabled": True, "co2_target": 700}),
    ]  # пределы 1..4 уже стоят — повторно не шлются
    attrs = hass.states.get(entity_id).attributes
    assert attrs["preset_mode"] == "eco" and attrs["target_co2"] == 700


async def test_command_error_is_shown_and_state_restored(hass, patched_cloud, cloud):
    await _setup(hass)
    entity_id = _climate(hass, BREEZER_4S)
    cloud.command_error = TionDeviceTimeoutError("timeout")
    with pytest.raises(HomeAssistantError, match="не ответило"):
        await hass.services.async_call("climate", "set_fan_mode", {"entity_id": entity_id, "fan_mode": "6"}, blocking=True)
    cloud.push(cloud.account)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).attributes["fan_mode"] == "3"


async def test_offline_gateway_makes_breezer_unavailable(hass, patched_cloud, cloud):
    await _setup(hass)
    account = cloud.account
    home = account.locations[0]
    devices = tuple(replace(d, is_online=False) if d.id == MAGICAIR else d for d in home.devices)
    cloud.push(replace(account, locations=(replace(home, devices=devices),)))
    await hass.async_block_till_done()
    assert hass.states.get(_climate(hass, BREEZER_4S)).state == "unavailable"


async def test_bad_entry_data_asks_to_sign_in(hass, patched_cloud):
    entry = await _setup(hass, data={"connection": "cloud_v4", "email": EMAIL})
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == ["reauth"]


# ---------- переезд со старого облака ----------

async def test_legacy_entry_moves_to_v4_ids_by_mac(hass, patched_cloud, cloud):
    """Запись старого облака: устройства с MAC и сущности под guid → новые ID, entity_id прежний."""
    old_guid = "9289c923-5665-4fd1-8259-28ce45668a81"
    mac_4s = cloud.account.device(BREEZER_4S).macs[0].upper()
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title=f"Tion ({EMAIL})",
        data={"connection": "cloud", "username": EMAIL, "password": "x"},
    )
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, old_guid)},
        connections={(dr.CONNECTION_NETWORK_MAC, mac_4s)},
        name="Спальня",
    )
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("climate", DOMAIN, old_guid, config_entry=entry,
                                device_id=device.id, suggested_object_id="tion_spalnia")
    ent_reg.async_get_or_create("sensor", DOMAIN, f"{old_guid}_speed", config_entry=entry,
                                device_id=device.id, suggested_object_id="tion_spalnia_speed")

    # что делает reauth-flow при переходе: data → v4, опции очищены
    hass.config_entries.async_update_entry(entry, data=V4_DATA, options={})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert ent_reg.async_get("climate.tion_spalnia").unique_id == BREEZER_4S
    assert ent_reg.async_get("sensor.tion_spalnia_speed").unique_id == f"{BREEZER_4S}_speed"
    assert hass.states.get("climate.tion_spalnia").attributes["fan_mode"] == "3"
    moved = dr.async_get(hass).async_get(device.id)
    assert (DOMAIN, BREEZER_4S) in moved.identifiers and (DOMAIN, old_guid) not in moved.identifiers


async def test_not_migrated_account_raises_issue(hass, patched_cloud, cloud):
    from homeassistant.helpers import issue_registry as ir

    home = cloud.account.locations[0]
    cloud.account = replace(cloud.account, locations=(replace(home, needs_migration=True),))
    entry = await _setup(hass)
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"account_not_migrated_{entry.entry_id}")


# ---------- config flow ----------

class FakeLoginAuth:
    def __init__(self, *_a, **_k):
        self.device_key = DEVICE_KEY
        self.async_get_confirmation_code = AsyncMock()
        self.async_check_confirmation_code = AsyncMock()
        self.async_get_token = AsyncMock(return_value=TOKENS)


@pytest.fixture
def login_auth():
    auth = FakeLoginAuth()
    with patch("custom_components.tion.cloud_v4.TionAuth", return_value=auth):
        yield auth


async def _through_captcha(hass, result):
    assert result["type"] is FlowResultType.EXTERNAL_STEP and result["step_id"] == "captcha"
    assert result["url"].endswith(f"/api/tion/captcha/{result['flow_id']}")
    assert result["url"].startswith("http://localhost/")
    # то же, что делает TionCaptchaView после POST токена со страницы
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"captcha_token": "tok"})
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE
    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def test_flow_v4_login(hass, login_auth):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["menu_options"] == ["cloud_v4", "cloud", "ble"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud_v4"})
    assert result["step_id"] == "cloud_v4"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": EMAIL, "password": "secret", "captcha_base_url": "http://localhost"},
    )
    result = await _through_captcha(hass, result)
    login_auth.async_get_confirmation_code.assert_awaited_once_with(EMAIL, "secret", "tok")
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "code"

    with patch("custom_components.tion.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": " 1234 "})
    login_auth.async_check_confirmation_code.assert_awaited_once_with("1234")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data["connection"] == "cloud_v4" and data["email"] == EMAIL
    assert data["captcha_base_url"] == "http://localhost"
    assert data["access_token"] == "access" and "password" not in data
    assert TionDeviceKey.from_pem(data["device_key"]).key_id() == DEVICE_KEY.key_id()
    assert result["result"].unique_id == EMAIL


async def test_flow_v4_captcha_rejected_returns_to_form(hass, login_auth):
    login_auth.async_get_confirmation_code.side_effect = TionLoginError("invalid_captcha")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud_v4"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL, "password": "secret", "captcha_base_url": "http://localhost"}
    )
    result = await _through_captcha(hass, result)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "cloud_v4"
    assert result["errors"] == {"base": "invalid_captcha"}


async def test_flow_v4_bad_captcha_url(hass, login_auth):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud_v4"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL, "password": "secret", "captcha_base_url": "localhost/x"}
    )
    assert result["errors"] == {"captcha_base_url": "invalid_captcha_url"}


async def test_flow_v4_aborts_when_legacy_entry_exists(hass, login_auth):
    MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data={"connection": "cloud", "username": EMAIL}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud_v4"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL.upper(), "password": "secret"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "legacy_configured"


async def test_legacy_options_start_migration_reauth(hass, login_auth):
    """Опция «перейти на облако v4» у старой записи → reauth → запись становится v4."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title=f"Tion ({EMAIL})",
        data={"connection": "cloud", "username": EMAIL, "password": "x"},
        options={"scan_interval": 120, "file_path": "tion_auth"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 120, "file_path": "tion_auth", "migrate_v4": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "migrate_v4" not in entry.options
    await hass.async_block_till_done()

    flows = [f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
             if f["context"]["source"] == "reauth"]
    assert len(flows) == 1 and flows[0]["step_id"] == "reauth_legacy"
    flow_id = flows[0]["flow_id"]
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"password": "secret", "captcha_base_url": "http://localhost"}
    )
    result = await _through_captcha(hass, result)
    assert result["step_id"] == "code"
    with patch("custom_components.tion.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(flow_id, {"code": "1234"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data["connection"] == "cloud_v4" and entry.data["email"] == EMAIL
    assert "password" not in entry.data
    assert entry.options == {}


async def test_v4_entry_has_no_options(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data=V4_DATA)
    entry.add_to_hass(hass)
    assert not entry.supports_options


async def test_fan_auto_in_room_without_configured_auto(hass, cloud):
    """Авторежим комнаты ещё не настраивался — облаку уходят все поля сразу."""
    from custom_components.tion.cloud_v4_devices import TionV4Coordinator

    calls = []

    async def set_auto(room_id, **changes):
        calls.append((room_id, changes))

    cloud.async_set_auto_control = set_auto
    entry = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data=V4_DATA)
    entry.add_to_hass(hass)
    coordinator = TionV4Coordinator(hass, entry, cloud)
    coordinator.build_devices()
    breezer = next(b for b in coordinator.breezers if b.guid == BREEZER_3S)
    assert breezer.zone.valid and breezer.zone.mode == "manual"
    breezer.zone.mode = "auto"
    await breezer.zone.async_send()
    room_id = cloud.account.device(BREEZER_3S).room_id
    assert calls == [(room_id, {"enabled": True, "speed_min": 1, "speed_max": 6, "co2_target": 800})]


async def test_legacy_login_refused_opens_v4_reauth(hass):
    """Старое облако не пустило (аккаунт перенесён) → запрос входа в облако v4."""
    class RefusingApi:
        authorization = None

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, data={"connection": "cloud", "username": EMAIL, "password": "x"},
    )
    entry.add_to_hass(hass)
    with patch("tion.TionApi", return_value=RefusingApi()):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [(f["context"]["source"], f["step_id"]) for f in flows] == [("reauth", "reauth_legacy")]


async def test_legacy_breezer_device_info_has_mac(hass):
    from datetime import timedelta

    from custom_components.tion import TionDataUpdateCoordinator
    from custom_components.tion.climate import TionClimate
    from test_climate_cloud import FakeCloudBreezer

    breezer = FakeCloudBreezer()
    breezer.macs = ("3A:BE:65:DF:0C:C2",)
    info = TionClimate(TionDataUpdateCoordinator(hass, timedelta(minutes=2)), breezer).device_info
    assert info["connections"] == {(dr.CONNECTION_NETWORK_MAC, "3A:BE:65:DF:0C:C2")}
