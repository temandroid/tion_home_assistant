# Бризеры Tion с Wi-Fi (приложение Tion Smart) → Home Assistant

> Для бризеров, работающих через приложение **Tion Smart**:
> **Tion 4S** с USB-модулем интеграции Wi-Fi, **4S TS**, **Breezer Bio X**.
>
> Старые бризеры со шлюзом MagicAir — не сюда, для них основная интеграция
> этого репозитория.

Эти бризеры работают на платформе **Tuya** (Tion Smart — OEM/white-label
приложение Tuya), поэтому интеграция через облако MagicAir с ними не работает.
Подключение — средствами экосистемы Tuya.

---

## Главное ограничение

«Простые» пути — штатная **Tuya**-интеграция HA и cloud-assisted setup в
**tuya-local** — принимают *user code* только от приложений **Smart Life** и
**Tuya Smart**. Код из Tion Smart отклоняется с ошибкой «код для другого
приложения»: у OEM-приложений отдельная схема аккаунтов, и аккаунты между
приложениями не общие.

Второй известный блокер: на `iot.tuya.com` в шаге **Link Tuya App Account**
QR-код часто показывает «QR code has expired» даже сразу после обновления.

---

## Путь 1 — локально через tuya-local (нужен local_key)

Полностью локальное управление по LAN (Tuya protocol 3.5), Tion Smart
продолжает работать. Требуется `local_key` устройства.

1. Установить **tuya-local**: HACS → Custom repositories → `old-atstec/tuya-local`
   (форк `make-all/tuya-local` со встроенным конфигом TION Breezer 4S; в upstream
   конфиг не принят, см. ниже) → Integration → Download → перезапуск HA.
2. Получить `device_id` и `local_key` устройства.
3. HA → Settings → Devices & Services → Add Integration → **Tuya Local** →
   ручная настройка: IP, device_id, local_key, protocol **3.5**.

Устройство сматчится с конфигом по `product_id`, появятся сущности: climate
(off/heat/fan_only, скорости 1–6, целевая и текущая температура, hvac_action),
переключатели звука/подсветки/рециркуляции, сенсоры уличной температуры,
мощности нагревателя и ресурса фильтра, binary_sensor проблемы.

> Способы добыть `local_key` при живом Tion Smart — предмет отдельного
> исследования, результаты будут добавлены в этот документ.

**Совет:** зарезервировать IP бризера за MAC-адресом в роутере.

---

## Путь 2 — облачный мост через Яндекс

Работает без `local_key`. Бризер привязывается к «Дому с Алисой» через навык
Smart Life (при входе выбирается white-label Tion Smart), а HACS-компонент
[`AlexxIT/YandexStation`](https://github.com/AlexxIT/YandexStation) импортирует
устройства умного дома Яндекса в HA. Физическая колонка не нужна.

Минус — облачный путь (Tuya → Яндекс → HA): задержка около секунды и
зависимость от интернета.

---

## Путь 3 — перепарка в Smart Life (ломает Tion Smart)

Если родное приложение не нужно: удалить бризер в Tion Smart → добавить в
**Smart Life** → взять user code (Settings → Account and Security → User Code)
→ cloud-assisted setup в tuya-local подтянет `device_id` и `local_key`
автоматически. Всё через UI, полностью локально.

Цена — Tion Smart устройство больше не увидит.

---

## Конфиги устройств

- [tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml) — TION Breezer 4S (проверен на физическом устройстве)
- [tion_bio_x_tuya_local.yaml](./tion_bio_x_tuya_local.yaml) — TION Breezer Bio X

В upstream `make-all/tuya-local` конфиги Tion не принимают: PR
[#5554](https://github.com/make-all/tuya-local/pull/5554) и
[#5561](https://github.com/make-all/tuya-local/pull/5561) отклонены мейнтейнером
по нетехническим мотивам. Форк с поддержкой 4S: `old-atstec/tuya-local`.

---

## Данные устройства (пример, Tion 4S + USB Wi-Fi модуль)

| Параметр | Значение |
|---|---|
| product_id | `rllylqfcd3lfe3s3` |
| protocol | 3.5 |
| порт | TCP 6668 |

`device_id`, `local_key` и IP — свои для каждого устройства.

---

## Troubleshooting

| Симптом | Что проверить |
|---|---|
| «Код для другого приложения» при вводе user code | Код от Tion Smart — принимаются только Smart Life / Tuya Smart |
| QR «expired» на iot.tuya.com | Инкогнито и чистые cookies, синхронизация часов ПК, скан в первые секунды после обновления, другой браузер |
| Устройство не матчится с конфигом | YAML в `custom_components/tuya_local/devices/`, product_id совпадает, HA перезапущен |
| Connection refused / timeout | Бризер в той же подсети, TCP 6668 не блокируется |
| `Invalid local_key` | Ключ меняется при каждой перепарке — получить заново |
| Сущности есть, но не реагируют | Tuya держит одну локальную сессию — закрыть Tion Smart на телефоне |
