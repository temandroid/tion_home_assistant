# Tion Breezer Bio X в Home Assistant

> **Эта интеграция (`tion_home_assistant`) для Bio X НЕ подходит.**
> Bio X — новая линейка (с февраля 2026), которая подключается напрямую по Wi-Fi
> через приложение **Tion Smart** (white-label от Tuya), а не через MagicAir-шлюз.
> Текущая интеграция работает только со старыми моделями (S3 / S4 / 4S + MagicAir).

Этот документ — инструкция как подключить Bio X к HA через **`tuya-local`**
(`make-all/tuya-local`), без облака и без зависимости от Tion Smart.

---

## Что получится

После настройки в HA появятся:

**Основные:**
- `switch.power` — питание
- `number.speed` (1-7) — скорость вентилятора
- `number.heater` (0-30°C) — целевая температура нагревателя
- `switch.recirculation_mode` — рециркуляция
- `sensor.indoor_temperature`, `sensor.outdoor_temperature`
- `sensor.co2`, `sensor.pm25`, `sensor.humidity` (есть только если установлен датчик)
- `sensor.filter_life` (%)

**Конфигурационные:**
- `switch.sleep`, `switch.sound`, `switch.auto_mode`
- `lock.child_lock`
- `light.indicator_light`
- `number.target_co2` (400-1500 ppm, шаг 50)
- `number.max_auto_speed`, `number.min_auto_speed`
- `number.target_filter_life` (дней)
- `select.panel_color`
- `button.filter_reset`, `button.calibrate_co2`

**Диагностические:** heater_type, total_work_time, error_code, heating, heater_power.

---

## Шаг 1. Установить `tuya-local`

HACS → Integrations → правый верх три точки → **Custom repositories**:
- Repository: `make-all/tuya-local`
- Category: `Integration`
→ Add → найти **Local Tuya** в списке → Download → перезапустить HA.

## Шаг 2. Добавить device YAML

Скопировать [`tion_bio_x_tuya_local.yaml`](./tion_bio_x_tuya_local.yaml) из этого репо в:

```
<HA config>/custom_components/tuya_local/devices/tion_breezer_bio_x.yaml
```

Перезапустить HA ещё раз.

> Почему вручную: PR [#4137](https://github.com/make-all/tuya-local/pull/4137) с этим
> конфигом был закрыт без merge. В составе `tuya-local` его пока нет.

## Шаг 3. Получить `device_id` + `local_key`

Это секреты для прямого локального подключения к бризеру по TCP. Два пути:

### Путь A — через Tuya IoT Platform (надёжно)

1. Регистрация на https://iot.tuya.com/ (Developer, бесплатно)
2. **Cloud → Create Cloud Project**:
   - Industry: *Smart Home*
   - Development Method: *Smart Home PaaS*
   - Data Center: тот, что ближе (Central Europe / India / China)
3. Внутри проекта → **Devices → Link Tuya App Account**:
   - Add App Account → отсканировать QR-код из Tion Smart
     (в приложении: Profile → Settings → … обычно есть пункт "Scan" или просто QR-сканер на главной)
4. Devices → должен появиться Bio X → нажать на иконку — там `Device ID` и `Local Key`.

### Путь B — `tinytuya wizard` (быстрее)

Всё равно нужен аккаунт iot.tuya.com (хотя бы для API key), но не нужно копаться в UI:

```bash
pip install tinytuya
python -m tinytuya wizard
```

Мастер спросит API Key/Secret (из Cloud project → Overview → Authorization Key) и
сам сохранит `devices.json` с device_id, local_key, ip всех твоих Tuya-устройств.

## Шаг 4. Найти IP бризера в локальной сети

В админке роутера → DHCP-leases / список клиентов → найти по MAC бризера.
Рекомендуется **зарезервировать IP за MAC** в роутере, чтобы не менялся.

## Шаг 5. Добавить устройство в HA

**Settings → Devices & Services → Add Integration → Local Tuya** → выбрать
*Add a new device*:

| Поле | Значение |
|---|---|
| Friendly name | `Tion Bio X` |
| Host | IP бризера |
| Device ID | из шага 3 |
| Local key | из шага 3 |
| Protocol version | `3.3` (если не работает — `3.4`) |
| Scan interval | 30 |

Дальше HA сам подберёт template `Tion Breezer Bio X` и создаст все entity'и.

---

## Альтернатива: официальная Tuya integration

Если возиться с iot.tuya.com не хочется:

**Settings → Devices & Services → Add Integration → Tuya** → войти аккаунтом Tion Smart.

Минус: на момент написания (май 2026) штатная интеграция показывает часть DP как
сырые числа — см. [HA issue #149874](https://github.com/home-assistant/core/issues/149874).
Управление работает, но красивых entity'ей вроде `number.target_co2` не будет.

---

## Troubleshooting

| Симптом | Что проверить |
|---|---|
| `Device matches xxx with quality of N%` в логах | YAML-файл не скопирован, либо `product_id` не совпадает с `9mqdhwklpvnnvb7t` |
| Connection refused / timeout | Бризер не в той же подсети что HA; firewall блокирует порт 6668 TCP |
| Wrong protocol version | Попробовать `3.3` → `3.4` → `3.2` |
| `Invalid local_key` | Перепарь устройство в Tion Smart — `local_key` меняется при каждом сопряжении. Перевытащи через шаг 3. |
| Entity'и появляются, но не реагируют | Бризер уже отвечает кому-то (приложению Tion Smart). Tuya разрешает только одну активную сессию — закрой приложение или используй cloud-режим. |
