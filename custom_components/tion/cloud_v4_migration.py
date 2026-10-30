"""Переезд записи со старого облака на v4 с сохранением entity_id и истории (CR-T-044).

У v4 другие ID устройств; общий у двух облаков только MAC. Старая облачная запись
с 1.4.0 кладёт MAC в реестр устройств (`connections`), и по нему v4-запись переносит
identifiers устройств и unique_id сущностей на новые ID.
Логика — из vaproloff/tion_home_assistant (MIT, коммит a25628d, `_migrate_old_ids`).
"""
from collections.abc import Mapping
import logging
from string import hexdigits

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)

from .cloud_v4 import TionAccount
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@callback
def async_migrate_old_ids(hass: HomeAssistant, entry: ConfigEntry, account: TionAccount) -> dict[str, str]:
    """Перенести устройства и сущности со старых ID на ID облака v4; вернуть {старый: новый}."""
    current = _current_ids_by_mac(account)
    device_registry = dr.async_get(hass)
    moves: dict[str, str] = {}
    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        old = {
            identifier
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN and account.device(identifier[1]) is None
        }
        if not old:
            continue
        if (current_id := _current_id(device_entry, current)) is None:
            _LOGGER.info(
                "Tion v4: для %s нет устройства с тем же MAC в новом облаке — "
                "останется под старым ID (сущности станут недоступны)",
                device_entry.name,
            )
            continue
        try:
            device_registry.async_update_device(
                device_entry.id,
                new_identifiers=(device_entry.identifiers - old) | {(DOMAIN, current_id)},
            )
        except dr.DeviceIdentifierCollisionError:
            _LOGGER.debug("Tion v4: ID %s уже занят другим устройством", current_id)
            continue
        moves.update((old_id, current_id) for _, old_id in old)

    moved_entities = 0
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if (unique_id := _moved_unique_id(entity.unique_id, moves)) is None:
            continue
        try:
            entity_registry.async_update_entity(entity.entity_id, new_unique_id=unique_id)
        except ValueError:
            _LOGGER.debug("Tion v4: unique_id %s уже занят", unique_id)
        else:
            moved_entities += 1
    if moves or moved_entities:
        _LOGGER.info(
            "Tion v4: %d устройств и %d сущностей перенесены на ID нового облака",
            len(set(moves.values())), moved_entities,
        )
    return moves


@callback
def async_update_migration_issue(hass: HomeAssistant, entry: ConfigEntry, account: TionAccount) -> None:
    """Подсказка в «Исправлениях», пока дом аккаунта не перенесён в приложении MagicAir."""
    issue_id = f"account_not_migrated_{entry.entry_id}"
    if any(location.needs_migration for location in account.locations):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="account_not_migrated",
            translation_placeholders={"email": entry.title},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _mac_value(mac: str) -> int | None:
    """MAC как число — независимо от разделителей, регистра и ведущих нулей."""
    digits = "".join(char for char in mac if char in hexdigits)
    if not digits:
        return None
    return int(digits, 16) or None


def _device_macs(device_entry: dr.DeviceEntry) -> list[str]:
    return [mac for kind, mac in device_entry.connections if kind == dr.CONNECTION_NETWORK_MAC]


def _current_ids_by_mac(account: TionAccount) -> dict[int, str]:
    """MAC → ID устройства; MAC, общий у нескольких устройств, пропускается."""
    owners: dict[int, set[str]] = {}
    for device in account.devices():
        for mac in device.macs:
            if (value := _mac_value(mac)) is not None:
                owners.setdefault(value, set()).add(device.id)
    return {value: next(iter(ids)) for value, ids in owners.items() if len(ids) == 1}


def _current_id(device_entry: dr.DeviceEntry, current: Mapping[int, str]) -> str | None:
    for mac in _device_macs(device_entry):
        if (value := _mac_value(mac)) is not None and value in current:
            return current[value]
    return None


def _moved_unique_id(unique_id: str, moves: Mapping[str, str]) -> str | None:
    """unique_id под новым ID устройства; None, если устройство не переезжало."""
    # По префиксу: новые ID могут содержать "_"
    for old_id, current_id in moves.items():
        if unique_id == old_id:
            return current_id
        if unique_id.startswith(f"{old_id}_"):
            return current_id + unique_id.removeprefix(old_id)
    return None
