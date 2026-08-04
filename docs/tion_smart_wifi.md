# Tuya OEM-устройства (Tion Smart, ALUTECH Smart) → Home Assistant

> Инструкция для устройств на Tuya-платформе, живущих в **родных OEM-приложениях**:
> - бризеры **Tion 4S** (USB Wi-Fi модуль) / **4S TS** / **Bio X** — приложение Tion Smart
> - ворота и роллеты **ALUTECH Smart** — тоже Tuya (Zigbee-хаб + Wi-Fi-модули)
>
> Старые бризеры с MagicAir-шлюзом — не сюда, для них основная интеграция этого репо.

## Главное ограничение

Все «простые» пути (штатная Tuya-интеграция HA, cloud-assisted setup в tuya-local)
принимают user code **только от Smart Life / Tuya Smart**. У OEM-приложений своя
схема аккаунтов — их коды отклоняются («код для другого приложения»), и аккаунты
между приложениями **не общие**.

Отсюда выбор:

| Требование | Путь |
|---|---|
| **Родные приложения должны работать** (Tion Smart, ALUTECH Smart) | **Путь 1** (Алиса → HA, облако) или **Путь 2** (local_key через iot.tuya.com, локально) |
| Родное приложение не нужно, важна локальность и простота | Путь 3 (перепарка в Smart Life + форк tuya-local) |

---

## Путь 1 (рекомендуется) — Алиса → HA через AlexxIT/YandexStation

Устройства остаются в родных приложениях, привязываются к «Дому с Алисой»
через навыки, а HACS-компонент [`AlexxIT/YandexStation`](https://github.com/AlexxIT/YandexStation)
импортирует их в HA как entity. **Физическая Яндекс-колонка не обязательна** —
достаточно аккаунта Яндекса.

```
Tion Smart ────┐
               ├─ Tuya cloud ─ навык Алисы ─ Дом с Алисой ─ YandexStation ─ HA
ALUTECH Smart ─┘
```

**Плюсы:** родные приложения работают, один механизм на все OEM-устройства
(бризер + ворота + роллеты), настройка ~30 минут.
**Минусы:** облачный путь (Tuya → Яндекс → HA), лаг ~0.5–1.5 с, зависимость от
интернета и облаков.

### Шаг 1. Привязать устройства к Алисе

- **Tion:** Дом с Алисой → Устройства → `+` → навык **Smart Life** → при входе
  выбрать white-label приложение Tion Smart, войти его кредами. (У пользователя
  это уже сделано в мае 2026.)
- **ALUTECH:** аналогично — навык **ALUTECH Smart** (или тот же Smart Life с
  выбором white-label), войти кредами приложения ALUTECH Smart.

Проверить: устройства видны и управляются в «Дом с Алисой».

### Шаг 2. Поставить YandexStation в HA

1. HACS → Integrations → поиск **Yandex.Station** (репо `AlexxIT/YandexStation`) → Download → перезапуск HA.
2. Settings → Devices & Services → Add Integration → **Yandex Station** →
   авторизация в аккаунте Яндекса (QR / логин).
3. В настройках интеграции включить импорт нужных устройств умного дома:
   бризер придёт как `climate`, ворота/роллеты — как `cover`.

Дальше — обычные HA-автоматизации поверх этих entity.

---

## Путь 2 (локальный, для энтузиастов) — local_key через iot.tuya.com

Единственный **полностью локальный** способ, при котором родные приложения
продолжают работать: привязка OEM-аккаунтов к developer-проекту Tuya
(read-only, устройства из приложений не исчезают) → получение `local_key` →
ручная настройка tuya-local.

1. https://iot.tuya.com → Cloud Project (Smart Home PaaS, DC **Central Europe**).
2. Devices → **Link Tuya App Account** → QR сканировать **самим OEM-приложением**
   (Tion Smart / ALUTECH Smart — у обоих есть сканер). Можно привязать несколько
   app-аккаунтов к одному проекту.
3. Devices → All Devices → скопировать `local_key` каждого устройства
   (или `tinytuya wizard` — вытащит всё в devices.json).
4. tuya-local (форк `old-atstec/tuya-local` — в нём конфиг 4S встроен) →
   Add Integration → **manual setup**: IP, device_id, local_key, protocol 3.5.

> ⚠️ Известный блокер: QR на шаге 2 может постоянно показывать «expired»
> (баг Tuya-портала, у пользователя воспроизводился в мае 2026). Workarounds:
> инкогнито-окно + чистые cookies, синхронизация часов ПК (`w32tm /resync /force`),
> обновить QR и сканировать в первые секунды, попробовать мобильный браузер,
> сменить браузер. Если QR так и не заработает — Путь 1.

Данные бризера для ручной настройки:

| Параметр | Значение |
|---|---|
| product_id | `rllylqfcd3lfe3s3` |
| device_id | `bf7af32b6fa1a72391lqy6` |
| IP | 192.168.254.153 (зарезервировать в роутере!) |
| protocol | 3.5 |

Для ворот ALUTECH product_id/DP неизвестны — после привязки смотреть
в проекте / tinytuya; в tuya-local есть готовые конфиги категории
garage door / curtain, может сматчиться сам.

---

## Путь 3 (максимально просто + локально, но БЕЗ родного приложения)

Перепарить устройство в **Smart Life** → форк `old-atstec/tuya-local` через
HACS → cloud-assisted setup (user code + QR из Smart Life) — всё через UI,
`local_key` подтянется сам. Подробности в истории репо (коммит `0bf90ad`).

Цена: Tion Smart / ALUTECH Smart устройство больше не увидят. Не подходит
при текущем требовании, оставлено для справки.

---

## Конфиги устройств (резервные копии в этом репо)

- [tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml) — TION Breezer 4S (проверен на физическом устройстве)
- [tion_bio_x_tuya_local.yaml](./tion_bio_x_tuya_local.yaml) — TION Breezer Bio X

В upstream `make-all/tuya-local` конфиги Tion не принимают (PR
[#5554](https://github.com/make-all/tuya-local/pull/5554)/[#5561](https://github.com/make-all/tuya-local/pull/5561)
отклонены мейнтейнером по политическим мотивам). Живой форк с 4S: `old-atstec/tuya-local`.

## Troubleshooting

| Симптом | Что проверить |
|---|---|
| «Код для другого приложения» при вводе user code | Код от OEM-приложения — cloud-assisted принимает только Smart Life / Tuya Smart. Использовать Путь 1 или Путь 2 |
| QR «expired» на iot.tuya.com | См. workarounds в Пути 2; если не помогло — Путь 1 |
| Алиса не видит устройство | Перепривязать навык, проверить что устройство онлайн в родном приложении |
| YandexStation не импортирует устройство | Проверить, что устройство видно в «Дом с Алисой»; обновить список в настройках интеграции |
| tuya-local: устройство не матчится с конфигом | product_id совпадает? YAML в `devices/`? HA перезапущен? |
| tuya-local: entity не реагируют | Tuya держит одну локальную сессию — закрыть родное приложение на телефоне |
