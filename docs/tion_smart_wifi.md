# Tion бризеры с Wi-Fi (приложение Tion Smart) → Home Assistant

> Эта инструкция — для бризеров Tion, которые подключаются по **Wi-Fi через
> приложение Tion Smart** (white-label Tuya). Не путать со старыми моделями,
> которые работают через шлюз MagicAir — для них основная интеграция этого репо.

Покрывает:
- **Tion 4S** с USB-модулем интеграции Wi-Fi (вышел в феврале 2026) — стартер-конфиг ниже
- **Tion 4S TS** (со встроенным Tuya-модулем)
- **Tion Breezer Bio X** — готовый конфиг [tion_bio_x_tuya_local.yaml](./tion_bio_x_tuya_local.yaml)

Подход одинаковый — `make-all/tuya-local` + device YAML.

---

## Общие шаги

### 1. Поставить `tuya-local` (`make-all/tuya-local`)

HACS → Integrations → правый верх три точки → **Custom repositories**:
- Repository: `make-all/tuya-local`
- Category: `Integration`
→ Add → найти **Local Tuya** в списке → Download → перезапустить HA.

### 2. Получить `device_id`, `local_key`, `product_id`

Один раз — нужен Tuya IoT developer-аккаунт (бесплатный).

#### Вариант A: `tinytuya wizard` (быстрее)

```bash
pip install tinytuya
python -m tinytuya wizard
```

Пройти шаги — в результате получишь `devices.json` со всеми Tuya-устройствами
твоего аккаунта Tion Smart: ip, device_id, local_key, **product_id**.

#### Вариант B: вручную через iot.tuya.com

1. https://iot.tuya.com → регистрация Developer → **Cloud → Create Cloud Project**
   (Industry: Smart Home, Method: Smart Home PaaS, Data Center: Central Europe / India)
2. Внутри проекта → **Devices → Link Tuya App Account → Add App Account →
   отсканировать QR из Tion Smart** (Profile → ... → Scan)
3. Devices → выбрать бризер → скопировать `Device ID` и `Local Key`.
4. Product ID видно в той же карточке устройства.

### 3. Найти IP бризера

В админке роутера → DHCP clients → найти по MAC. Зарезервировать IP за MAC.

### 4. Поставить device YAML в HA

Скопировать соответствующий файл в:
```
<HA config>/custom_components/tuya_local/devices/<имя>.yaml
```

- Для **Bio X**: [tion_bio_x_tuya_local.yaml](./tion_bio_x_tuya_local.yaml) → `tion_breezer_bio_x.yaml`
- Для **4S**: см. ниже — нужно сделать на основе реальных DPS твоего модуля

Перезапустить HA.

### 5. Добавить устройство в HA

**Settings → Devices & Services → Add Integration → Local Tuya → Add a new device**:

| Поле | Значение |
|---|---|
| Friendly name | `Tion 4S` (или `Tion Bio X`) |
| Host | IP из шага 3 |
| Device ID | из шага 2 |
| Local key | из шага 2 |
| Protocol version | `3.3` (если не работает — `3.4`) |
| Scan interval | 30 |

После — HA должен подцепить шаблон по `product_id` и создать entity'и.

---

## Tion 4S USB Wi-Fi — как сделать YAML

Готового конфига нет, но есть рабочий путь.

### Шаг 1: достать сырые DPS

После шага 2 общей инструкции у тебя есть `device_id` и `local_key`.
Запросить актуальное состояние всех DPS:

```bash
python -m tinytuya scan        # IP и product_id, если ещё не знаешь
```

Затем точечно по устройству:

```python
import tinytuya, json
d = tinytuya.OutletDevice('DEVICE_ID', 'IP', 'LOCAL_KEY')
d.set_version(3.3)             # или 3.4
print(json.dumps(d.status(), indent=2))
```

Получишь что-то вида:
```json
{
  "dps": {
    "101": true,           // power
    "102": 2,              // speed
    "103": false,          // sound
    "105": false,          // recirculation/heater enabled
    "106": 800,            // co2 (?)
    "108": 22,             // indoor/outdoor temp
    "114": 18,             // target heater temp
    "115": 87,             // filter life %
    ...
  }
}
```

### Шаг 2: пощёлкать кнопки в приложении и записать что меняется

В Tion Smart на телефоне — менять скорость, температуру, гейт, режим — и
каждый раз снимать `d.status()`. Записать, какой dps id за что отвечает.

> У 4S заведомо **нет**: PM2.5, влажности, цветной панели, calibrate CO2.
> CO2 — только если подключён MagicAir (но если у тебя MagicAir, ты бы
> использовал основную интеграцию, не Tuya).

### Шаг 3: стартер-YAML на основе Bio X (минус то, чего нет в 4S)

Создать в HA как `custom_components/tuya_local/devices/tion_breezer_4s.yaml`:

```yaml
name: Tion 4S
products:
  - id: ЗАМЕНИ_НА_СВОЙ_PRODUCT_ID    # из tinytuya wizard
    manufacturer: Tion
    model: Breezer 4S
entities:
  - entity: switch
    name: "Power"
    icon: "mdi:power"
    dps:
      - id: 101
        name: switch
        type: boolean
  - entity: number
    name: "Speed"
    icon: "mdi:fan"
    dps:
      - id: 102
        name: value
        type: integer
        range:
          min: 0
          max: 6                       # у 4S 0-6 (у Bio X 1-7)
  - entity: number
    name: "Target heater"
    icon: "mdi:thermometer-plus"
    dps:
      - id: 114
        name: value
        type: integer
        unit: C
        range:
          min: 0
          max: 30
  - entity: switch
    name: "Heater enabled"
    icon: "mdi:radiator"
    dps:
      - id: 105                        # ПРОВЕРИТЬ: 105 у Bio X = recirc, у 4S возможно heater
        name: switch
        type: boolean
  - entity: sensor
    name: "Indoor temperature"
    class: temperature
    dps:
      - id: 108
        name: sensor
        type: integer
        unit: "°C"
  - entity: sensor
    name: "Outdoor temperature"
    class: temperature
    dps:
      - id: 112                        # ПРОВЕРИТЬ
        name: sensor
        type: integer
        unit: "°C"
  - entity: sensor
    name: "Filter life"
    icon: "mdi:air-filter"
    dps:
      - id: 115
        name: sensor
        type: integer
        unit: "%"
  - entity: switch
    name: "Sound"
    category: config
    icon: "mdi:volume-high"
    dps:
      - id: 103
        name: switch
        type: boolean
  - entity: light
    name: "Indicator light"
    category: config
    dps:
      - id: 104
        name: brightness
        type: string
        mapping:
          - dps_val: "0"
            value: 0
          - dps_val: "50"
            value: 128
          - dps_val: "100"
            value: 255

# TODO ниже — пощёлкать и понять, что соответствует:
# - выбор источника воздуха (улица / квартира / смешанный) — какой DPS меняется?
#   возможно отдельный switch, возможно select с тремя значениями
# - режим (manual / auto) — если нет MagicAir, auto может вообще отсутствовать
# - sleep / boost пресеты — если в приложении есть кнопки, должны быть DPS
```

### Шаг 4: проверить через HA

Перезапустить HA → добавить устройство → если в логах
`Device matches tion_breezer_4s with quality of 100%` — твой YAML маппится
правильно. Если меньше (например 60%) — какие-то DPS лишние или отсутствуют.

### Шаг 5 (опционально): отправить в upstream

Если работает — отправь PR в [`make-all/tuya-local`](https://github.com/make-all/tuya-local).
Issue #4853 как раз ждёт чьего-нибудь рабочего конфига.

---

## Troubleshooting

| Симптом | Что проверить |
|---|---|
| `Device matches xxx with quality of N%` в логах | YAML-файл не скопирован / `product_id` не совпадает / DPS не маппятся |
| Connection refused / timeout | Бризер не в той же подсети что HA; firewall блокирует TCP 6668 |
| Wrong protocol version | Перебрать `3.3` → `3.4` → `3.2` |
| `Invalid local_key` | Перепарь устройство в Tion Smart — `local_key` меняется при сопряжении. Перевытащи через iot.tuya.com / tinytuya |
| Entity'и появляются, но не реагируют | Tuya разрешает только одну активную сессию. Закрой приложение Tion Smart на телефоне — оно держит соединение |
| Управление работает с лагами | Уменьши scan_interval, проверь Wi-Fi-канал бризера |

## Альтернатива: официальная Tuya integration HA

Если возиться не хочется — `Settings → Add Integration → Tuya` → войти аккаунтом Tion Smart.
Cloud-only, может не маппить все параметры красиво, но управление будет.
