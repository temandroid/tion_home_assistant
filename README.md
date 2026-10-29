# Tion Home Assistant

Форк модуля Tion_Home_Assistant от Valeriy Chistyakov (спасибо ему!) с
доработками: config flow (UI-настройка), DataUpdateCoordinator, режим Bluetooth
для 4S без облака, фиксы по code-review. Текущая версия — **1.3.1**, история
изменений — в [CHANGELOG.md](CHANGELOG.md), релизы — на странице
[Releases](https://github.com/temandroid/tion_home_assistant/releases).

## Какой у вас бризер? Выберите путь

| Ваш бризер | Приложение | Путь |
|---|---|---|
| Бризер + шлюз **MagicAir** (S3/S4/4S/Lite через облако MagicAir) | MagicAir | **Эта интеграция**, облачный режим — см. ниже |
| **4S** (с MagicAir или без) — напрямую по Bluetooth, без облака | Tion Remote | **Эта интеграция**, режим Bluetooth — [ниже](#bluetooth-tion-4s-без-облака-v130) |
| **4S с USB Wi-Fi модулем**, **4S TS**, **Bio X** | Tion Smart | Tuya-стек — [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md) |

Новые бризеры с Wi-Fi работают на платформе Tuya, а не через облако MagicAir —
**эта интеграция для них не подходит**. Способы подключить их к Home Assistant
собраны в [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md).

---

## Интеграция MagicAir (этот репозиторий)

Управление бризерами Tion и чтение датчиков MagicAir через облако MagicAir.
Основано на пакете [tion](https://github.com/airens/tion).

*Для работы требуется шлюз MagicAir!*

### Установка

**HACS:** Custom repositories → `temandroid/tion_home_assistant` (Integration) → установить.

**Без HACS:** скопировать `custom_components/tion` в `config/custom_components/`.

### Настройка (v1.2.0+, через UI)

1. Перезагрузите Home Assistant
2. `Settings → Devices & Services → Add Integration → Tion`
3. Введите email/пароль от облака MagicAir — будет произведена проверка

Опции (период опроса, путь к файлу авторизации) — кнопка **Configure** у интеграции.

<details>
<summary>Backward-compat: настройка через YAML (deprecated)</summary>

Старый блок `tion:` в `configuration.yaml` ещё работает — при старте HA он
автоматически импортируется в config entry (с deprecation-warning). После
импорта YAML-секцию рекомендуется удалить.

```yaml
# DEPRECATED — будет автоматически импортировано в UI
tion:
  username: !secret tion_email
  password: !secret tion_password
  scan_interval: 600
  file_path: "/tmp/tion_auth"
```
</details>

### Использование

После настройки появятся бризеры `climate.tion_...` и датчики MagicAir
`sensor.magicair_...`. Climate и сенсоры бризера группируются в одно
устройство.

Если облако не принимает команду, Home Assistant покажет ошибку, а состояние
перечитается из облака (до 1.3.1 такие команды терялись молча). Если облако
недоступно, сущности становятся `unavailable`, а не показывают старые данные.

#### climate.set_fan_mode
`fan_mode` задаёт скорость бризера (тип — строка):
- `off`, `0` — выключить
- `1`–`6` — ручной режим с заданной скоростью
- `auto` — автоматическое управление по уровню CO2
  (порог — `target_co2`, меняется только через пресеты AWAY/ECO)

#### climate.set_hvac_mode
- `heat` — нагреватель включен
- `fan_only` — нагреватель выключен
- `off` — прибор выключен

#### climate.turn_off / climate.turn_on
- `turn_off` — то же, что `hvac_mode: off`: зона переводится в ручной режим,
  иначе авто-режим MagicAir включил бы бризер обратно
- `turn_on` — включает бризер: по Bluetooth с прежней скоростью, через облако — со скоростью 1

#### climate.set_temperature
Целевая температура нагревателя.

#### climate.set_swing_mode
Источник потока воздуха:
- `vertical` — воздух из квартиры
- `both` — смешанный
- `horizontal` — воздух с улицы

#### climate.set_preset_mode

| Пресет | Поток | Скорость | Нагрев | Режим |
|---|---|---|---|---|
| `sleep` | улица | 1 | выкл | ручной |
| `activity` | улица | 2 | выкл | ручной |
| `boost` | улица | 6 | выкл | ручной |
| `home` | квартира | 2 | выкл | ручной |
| `comfort` | смешанный | 3 | выкл | ручной |
| `away` | улица | 1–6 | выкл | AUTO, target_co2=600 |
| `eco` | улица | 1–4 | выкл | AUTO, target_co2=700 |

Пресет сбрасывается в `none`, как только скорость, заслонку или режим меняют
вручную: после этого состояние бризера ему уже не соответствует. Без датчика
MagicAir пресеты `away`/`eco` недоступны.

## Bluetooth: Tion 4S без облака (v1.3.0+)

Бризер 4S управляется напрямую по BLE через стек `bluetooth` Home Assistant:
встроенный адаптер хоста или [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/).
Протокол — по [dentra/esphome-tion](https://github.com/dentra/esphome-tion). Одна запись = один бризер.

**Что нужно**
- Адаптер или прокси в нескольких метрах от каждого бризера. Прокси — ESP32/ESP32-S3
  (ESP-IDF), `bluetooth_proxy: active: true`; один прокси держит 3–4 активных подключения.
  Интеграция подключается только на время опроса/команды и отключается через 15 с тишины.
- Бризер держит **одно** BLE-подключение. Пока к нему подключены MagicAir или приложение,
  HA не подключится — MagicAir нужно отвязать или выключить.
- Прошивка бризера не ниже `02D2` (рекомендуется `04C7`; `02D0` и `03CD` не работают) —
  требование esphome-tion, проверить можно в приложении Tion Remote.

**Настройка**
1. `Settings → Devices & Services → Add Integration → Tion → Bluetooth`.
2. Выберите бризер из найденных или впишите MAC-адрес вручную (вида `AA:BB:CC:DD:EE:FF`;
   поле принимает свой адрес, даже если список не пуст), задайте название.
3. Переведите бризер в режим сопряжения: в режиме ожидания (жёлтый индикатор) удерживайте
   кнопку ~5 с до мигания синим — и нажмите «Подтвердить». Интеграция выполнит BLE-сопряжение
   и проверит, что это 4S.

**Отличия от облака:** нет авто-режима по CO2 (`fan_mode: auto`, пресеты `away`/`eco`) —
он живёт в MagicAir; заслонка только «улица» (`horizontal`) или «квартира» (`vertical`),
смешанного режима у 4S нет. Период опроса — 60 с по умолчанию (15–600, кнопка **Configure**).

### Тесты

```bash
python -m pytest tests/test_ble_protocol.py   # протокол, без Home Assistant
# полный набор — в Linux/WSL с pytest-homeassistant-custom-component и пакетом tion
python -m pytest tests
```

### Если что-то не работает

Расширенное логирование в `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.tion: debug
    tion: info
```

С 1.3.1 интеграция не пишет в лог токен авторизации. Всё равно просмотрите лог,
прежде чем выкладывать его в issue: там могут быть ваш email и названия устройств.
