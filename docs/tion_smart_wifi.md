# Tion бризеры с Wi-Fi (приложение Tion Smart) → Home Assistant

> Эта инструкция — для бризеров Tion, которые подключаются по **Wi-Fi через
> приложение Tion Smart** (white-label Tuya). Не путать со старыми моделями,
> которые работают через шлюз MagicAir — для них основная интеграция этого репо.

Покрывает:
- **Tion 4S** с USB-модулем интеграции Wi-Fi (вышел в феврале 2026) — **готовый конфиг!**
- **Tion 4S TS** (со встроенным Tuya-модулем)
- **Tion Breezer Bio X** — готовый конфиг

---

## Путь 1 (рекомендуется, актуально с августа 2026) — tuya-local с cloud-assisted setup

**Что изменилось:** современный `make-all/tuya-local` умеет **cloud-assisted
setup** — авторизация по **user code + QR из приложения Smart Life**, БЕЗ
developer-аккаунта на iot.tuya.com. `device_id` и `local_key` подтягиваются
автоматически. Старый блокер (протухающий QR при «Link App Account» на
iot.tuya.com) больше не актуален — этот шаг вообще не нужен.

Плюс появился **проверенный на физическом устройстве YAML-конфиг для 4S**
(product_id `rllylqfcd3lfe3s3`, protocol 3.5) — см.
[tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml).

> ⚠️ В upstream `make-all/tuya-local` конфиги Tion **не принимают** (мейнтейнер
> отклонил PR [#5554](https://github.com/make-all/tuya-local/pull/5554) /
> [#5561](https://github.com/make-all/tuya-local/pull/5561) по политическим
> мотивам). Поэтому YAML ставится вручную. Живой форк с конфигом:
> `old-atstec/tuya-local`.

**Что получится (entity'и для 4S):**
- `climate` — off / heat / fan_only, скорости 1–6, целевая и текущая температура, hvac_action (heating/idle)
- `switch` — sound, backlight, recirculation
- `sensor` — outdoor temperature, heater power (Вт), filter life (%)
- `binary_sensor` — problem (код ошибки в атрибуте description)

(CO2 у 4S нет — датчик CO2 живёт в MagicAir, а это другая экосистема.)

### Шаг 1. Установить tuya-local

HACS → Integrations → Custom repositories → `make-all/tuya-local`,
Category: Integration → Download → перезапуск HA.

### Шаг 2. Положить YAML-конфиг 4S

Скопировать [tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml) в:

```
<HA config>/custom_components/tuya_local/devices/tion_breezer_4s.yaml
```

Ещё раз перезапустить HA.

### Шаг 3. Получить user code в Smart Life

1. Поставить приложение **Smart Life** (если ещё нет) и войти **теми же
   email/паролем, что в Tion Smart** — базы аккаунтов общие.
2. Smart Life → **Settings → Account and Security → User Code** — записать код.

### Шаг 4. Добавить устройство в HA

**Settings → Devices & Services → Add Integration → Tuya Local**:

1. Выбрать **cloud-assisted setup**.
2. Ввести **user code** из шага 3 → HA покажет QR.
3. Отсканировать QR **приложением Smart Life** (Me → иконка сканера).
4. Выбрать бризер из списка устройств — `device_id`, `local_key`, IP и
   protocol (3.5) подставятся автоматически.
5. tuya-local сматчит устройство с конфигом `TION Breezer 4S` по product_id.

Если матчинг не сработал (в логах `Device matches ... with quality of N%` c
чужим именем) — проверить, что YAML лежит в правильной папке и product_id
в нём совпадает с фактическим.

**Совет:** зарезервировать IP бризера за MAC в роутере, чтобы не менялся.

---

## Путь 2 — через Яндекс.Алису (запасной)

Бризер подключается к Алисе через навык **Smart Life** (вход теми же
кредами, что в Tion Smart). Дальше пробрасываем из Алисы в HA через
HACS-интеграцию Yandex → HA.

**Минусы:** облако Яндекса — лаг 0.5-1 с, зависимость от интернета.
Использовать, если Путь 1 почему-то не взлетел.

1. Дом с Алисой → Устройства → `+` → Производитель → Smart Life → войти
   кредами Tion Smart → бризер появится в Алисе.
2. HACS-интеграция для проброса Yandex → HA — подобрать при настройке.

---

## Путь 3 — официальная Tuya integration HA (запасной)

Settings → Add Integration → **Tuya** → вход тоже по user code + QR из
Smart Life. Работает без дополнительных файлов, но категория бризеров
маппится неполно (часть DP — сырые числа, см. закрытый
[issue #149874](https://github.com/home-assistant/core/issues/149874)).
Базовое управление есть, детальной телеметрии нет. Cloud-only.

---

## Данные устройства пользователя (для отладки)

| Параметр | Значение |
|---|---|
| Модель | Tion 4S + USB Wi-Fi модуль |
| product_id | `rllylqfcd3lfe3s3` |
| device_id | `bf7af32b6fa1a72391lqy6` |
| IP | 192.168.254.153 |
| Tuya protocol | 3.5 |
| DC аккаунта | Central Europe |

## Troubleshooting

| Симптом | Что проверить |
|---|---|
| Устройство не матчится с конфигом | YAML в `devices/`, product_id совпадает, HA перезапущен |
| Connection refused / timeout | Бризер в той же подсети, TCP 6668 не блокируется |
| `Invalid local_key` | Ключ сменился после перепарки — пройти cloud-assisted setup заново |
| Entity'и есть, но не реагируют | Tuya держит одну локальную сессию — закрыть Tion Smart на телефоне |
| Состояние обновляется с лагом | Это push-протокол, лага быть не должно — проверить Wi-Fi бризера |
