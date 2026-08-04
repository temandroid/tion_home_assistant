# Tion бризеры с Wi-Fi (приложение Tion Smart) → Home Assistant

> Эта инструкция — для бризеров Tion, которые подключаются по **Wi-Fi через
> приложение Tion Smart** (white-label Tuya). Не путать со старыми моделями,
> которые работают через шлюз MagicAir — для них основная интеграция этого репо.

Покрывает:
- **Tion 4S** с USB-модулем интеграции Wi-Fi (вышел в феврале 2026) — **готовый конфиг!**
- **Tion 4S TS** (со встроенным Tuya-модулем)
- **Tion Breezer Bio X** — готовый конфиг

---

## Путь 1 (рекомендуется, актуально с августа 2026) — форк tuya-local, всё через UI

Никаких ручных YAML-файлов и developer-аккаунта Tuya:

- Форк **`old-atstec/tuya-local`** — это `make-all/tuya-local` со **встроенной
  поддержкой TION Breezer 4S** (product_id `rllylqfcd3lfe3s3`, protocol 3.5,
  DP проверены на физическом устройстве). Форк версионируется (2026.7.x)
  и ставится через HACS.
- **Cloud-assisted setup** в конфиг-флоу: авторизация по **user code + QR из
  Smart Life** — `device_id` и `local_key` подтягиваются автоматически.
  iot.tuya.com не нужен.

> Почему форк: мейнтейнер upstream отклонил PR с поддержкой Tion
> ([#5554](https://github.com/make-all/tuya-local/pull/5554) /
> [#5561](https://github.com/make-all/tuya-local/pull/5561)) по политическим
> мотивам — в `make-all/tuya-local` конфиг не появится.

**Что получится (entity'и для 4S):**
- `climate` — off / heat / fan_only, скорости 1–6, целевая и текущая температура, hvac_action (heating/idle)
- `switch` — sound, backlight, recirculation
- `sensor` — outdoor temperature, heater power (Вт), filter life (%)
- `binary_sensor` — problem (код ошибки в атрибуте description)

(CO2 у 4S нет — датчик CO2 живёт в MagicAir, а это другая экосистема.)

### Шаг 1. Установить форк tuya-local

HACS → Integrations → Custom repositories → `old-atstec/tuya-local`,
Category: Integration → Download → перезапуск HA.

> Если уже стоит `make-all/tuya-local` — удалить его сначала, две копии
> tuya_local конфликтуют.

### Шаг 2. Перепарить бризер в Smart Life

> ⚠️ **Важно:** user code привязан к схеме конкретного приложения. Tion Smart —
> OEM-приложение со своей схемой аккаунтов, и его код cloud-assisted setup
> **не принимает** (ошибка «код для другого приложения»). Поддерживаются только
> **Smart Life** и **Tuya Smart**. Аккаунты между приложениями НЕ общие —
> вход в Smart Life кредами Tion Smart даст пустой аккаунт без устройств.
> Поэтому бризер нужно перенести в Smart Life.

1. Поставить приложение **Smart Life**, зарегистрировать аккаунт (регион — Россия/Европа).
2. В **Tion Smart** удалить бризер (настройки устройства → Remove device) —
   модуль вернётся в режим сопряжения. Если нет — зажать кнопку на
   USB-модуле до мигания индикатора.
3. В **Smart Life** → `+` → Add Device → следовать мастеру Wi-Fi-сопряжения.
   Панель управления бризером подтянется автоматически — это тот же Tuya-стек.
4. Smart Life → **Settings → Account and Security → User Code** — записать код.

**Последствия перепарки:**
- Приложение Tion Smart устройство больше не увидит (управление — Smart Life / HA / Алиса).
- `local_key` сменится — не страшно, cloud-assisted setup вытянет новый сам.
- Навык Алисы перепривязать на аккаунт Smart Life (Дом с Алисой → Smart Life → войти новыми кредами).
- Вернуть бризер в Tion Smart можно в любой момент той же процедурой в обратную сторону.

### Шаг 3. Добавить устройство в HA

**Settings → Devices & Services → Add Integration → Tuya Local**:

1. Выбрать **cloud-assisted setup**.
2. Ввести **user code** из шага 2 → HA покажет QR.
3. Отсканировать QR **приложением Smart Life** (Me → иконка сканера).
4. Выбрать бризер из списка устройств — `device_id`, `local_key`, IP и
   protocol (3.5) подставятся автоматически.
5. tuya-local сматчит устройство с конфигом `TION Breezer 4S` по product_id.

**Совет:** зарезервировать IP бризера за MAC в роутере, чтобы не менялся.

### Bio X / если конфига нет в форке

Для Bio X конфиг в форк не входит — положить
[tion_bio_x_tuya_local.yaml](./tion_bio_x_tuya_local.yaml) вручную в
`<HA config>/custom_components/tuya_local/devices/`. Копия конфига 4S на
всякий случай тоже лежит рядом:
[tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml).

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
| «Код для другого приложения» при вводе user code | Код взят из Tion Smart (OEM) — поддерживаются только Smart Life / Tuya Smart. Перепарить бризер в Smart Life (Шаг 2) и взять код там |
| Устройство не матчится с конфигом | YAML в `devices/`, product_id совпадает, HA перезапущен |
| Connection refused / timeout | Бризер в той же подсети, TCP 6668 не блокируется |
| `Invalid local_key` | Ключ сменился после перепарки — пройти cloud-assisted setup заново |
| Entity'и есть, но не реагируют | Tuya держит одну локальную сессию — закрыть Tion Smart на телефоне |
| Состояние обновляется с лагом | Это push-протокол, лага быть не должно — проверить Wi-Fi бризера |
