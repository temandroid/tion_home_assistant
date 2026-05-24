# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [1.2.0] - 2026-05-24
### Изменения
#### Миграция на config_flow (CR-009, CR-014)
  - **CR-009:** Добавлена UI-конфигурация через `Settings → Devices & Services → Add Integration → Tion`. Логин/пароль вводятся в форме, валидируются на лету. Опции (`scan_interval`, `file_path`) меняются через `OptionsFlow` без пересоздания entry.
  - **CR-014:** Credentials хранятся в зашифрованном `.storage/core.config_entries` (HA-managed), не в plaintext-yaml.
  - Backward-compat: старый `tion:` блок в `configuration.yaml` автоматически импортируется в config entry при первом запуске (с deprecation-warning в лог).
  - Переписан `__init__.py`: `async_setup_entry` / `async_unload_entry` / `_async_update_listener` для reload при смене опций.
  - Платформы (`climate`, `sensor`) переведены с `setup_platform` (`discovery.load_platform`) на `async_setup_entry`.
  - Добавлены переводы UI: `translations/en.json`, `translations/ru.json`.
  - Вынесены константы в `const.py` (`DOMAIN`, `PLATFORMS`, `DATA_*` и др.).
  - `manifest.json`: `"config_flow": true`.

## [1.1.0] - 2026-05-24
### Изменения
#### Исправления по результатам code-review (CR-001..018, кроме CR-009/014)
  - **CR-001:** `setup()` → `async_setup()` с `async_add_executor_job` — больше не блокирует event loop HA при авторизации и discovery.
  - **CR-002:** Введён `DataUpdateCoordinator` — один периодический `.load()` на все устройства вместо N×HTTP per-entity. Сущности теперь `CoordinatorEntity`.
  - **CR-003:** Убран `assert api.authorization` — возвращается `False` с понятным логом.
  - **CR-004:** Если устройство/зона не найдены — `PlatformNotReady` вместо `IndexError`.
  - **CR-005:** `set_preset_mode` переписан через декларативную таблицу `PRESETS` — нет копипасты веток.
  - **CR-006:** `set_fan_mode(FAN_AUTO)` больше не сбрасывает `target_co2` в 600 — теперь target управляется только через preset (ECO/AWAY).
  - **CR-007:** Preset восстанавливается после рестарта HA через `RestoreEntity`.
  - **CR-008:** `manifest.codeowners` → `["@temandroid"]` (валидный формат для hassfest).
  - **CR-010:** `fan_modes` — чистые строки, без миксов типов.
  - **CR-011:** `unique_id` сенсора — стабильный ключ (`<guid>_<key>`) вместо конкатенации с именем (содержавшим пробел).
  - **CR-012:** `fan_state` защищён от `speed is None`.
  - **CR-013:** Добавлен `.gitignore` (особенно для `tion_auth` — OAuth-токена).
  - **CR-015:** Runtime-проверка версии HA сведена к одному модульному флагу `_HA_GE_2024_2`.
  - **CR-016:** `type(device) ==` → `isinstance` (поддержка наследников).
  - **CR-017:** Логи в getter'ах → DEBUG (`preset_mode`); setter'ы — кратко и через `%s`-форматирование.
  - **CR-018:** Маппинг `gate ↔ swing`/строка вынесен в модульные dict'ы.
  - Bump манифеста с `documentation` и `issue_tracker` на `temandroid/tion_home_assistant`.

## [1.0.9] - 2024-02-13
### Изменения
  - Поправил код на соответствие новой версии НА, начиная с 2024.2
    (https://developers.home-assistant.io/blog/2024/01/24/climate-climateentityfeatures-expanded)

## [1.0.8] - 2024-02-10
### Изменения
  - Изменение нумерации версий, для соотвествия AwesomeVersion 
  - Обновление манифеста для соответствия требованиям НА 2024.2
  - Исправление ошибки включения TION через сервис обогрева. Переключение на вентилятор было, а скорость не включалась. И бризер оставался выключеным по факту.

## [1.07] - 2024-02-08
### Изменения
#### Исправил баг режима AUTO.
  - После включения режима AUTO отключить режим можно было только через PRESET.
  - Сейчас при установке скорости 1-6 режим AUTO отключается

## [1.06] - 2024-02-04
### Изменения
#### Поменял настройки режима AUTO.
  - Сейчас реально работает по параметру target_co2.
  - Скорость 1-6
  - Забор воздуха с улицы
  - target_co2 = 800 по дефолту. Изменить можно ТОЛЬКО через пресеты, сделал 2 пресета для этого.
####
#### Изменен пресет: 
  - PRESET_AWAY: Режим AUTO, target_c02 = 600, с улицы, скорость 1-6, обогреватель выключен
####
#### Добавлен пресет:
  - PRESET_ECO:  Режим AUTO, target_c02 = 700, с улицы, скорость 1-4, обогреватель выключен
####
#### Пресеты без изменения:
    PRESET_SLEEP:    с улицы,     скорость 1, обогреватель выключен
    PRESET_ACTIVITY: с улицы,     скорость 2, обогреватель выключен
    PRESET_BOOST:    с улицы,     скорость 6, обогреватель выключен
    PRESET_HOME:     из квартиры, скорость 2, обогреватель выключен           
    PRESET_COMFORT:  смешанный,   скорость 3, обогреватель выключен 

## [1.05] - 2024-01-24
### Изменения
#### Поменял управление потоком воздуха. 
  Сейчас управления потоком сделано через свойство SWING (Режим качания). 
     SWING_VERTICAL = воздух из квартиры
     SWING_BOTH = смешанный
     SWING_HORIZONTAL = воздух с улицы
####
#### Переделал все пресеты на более нормальные, которые как-то соответствуют названию:
    PRESET_SLEEP:    с улицы,     скорость 1, обогреватель выключен
    PRESET_ACTIVITY: с улицы,     скорость 2, обогреватель выключен
    PRESET_BOOST:    с улицы,     скорость 6, обогреватель выключен
    PRESET_HOME:     из квартиры, скорость 2, обогреватель выключен           
    PRESET_COMFORT:  смешанный,   скорость 3, обогреватель выключен 
    PRESET_AWAY:     с улицы,     скорость 1, обогреватель выключен


## [1.03] - 2022-11-10
### Added
- библиотека Tion обновлена до 1.28. Исправлена работа 4S с нагревателем

## [1.02] - 2022-11-10
### Added
- библиотека Tion обновлена до 1.27

## [1.01] - 2022-11-10
### Added
- добавлена поддержка HVAC_MODE_OFF, версия библиотеки tion обновлена до 1.26
