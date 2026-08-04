# Бризеры Tion с Wi-Fi (приложение Tion Smart) → Home Assistant, локально

> Для бризеров на платформе **Tuya** (приложение **Tion Smart**): Tion 4S с
> USB-модулем интеграции Wi-Fi, 4S TS, Bio X. Старые бризеры со шлюзом
> MagicAir — не сюда, для них основная интеграция этого репозитория.
>
> Цель этого документа — **локальное** управление по LAN, **не ломая** родное
> приложение Tion Smart.

Локальный протокол Tuya (TCP 6668) уже открыт на устройстве — `tinytuya scan`
видит бризер. Не хватает единственного секрета — **`local_key`**. Вся задача
сводится к тому, чтобы его добыть.

---

## Почему облачные пути НЕ работают (не тратьте время)

Оба «простых» способа получить `local_key` через облако Tuya закрыты
**архитектурно**, а не из-за настроек:

- **iot.tuya.com → Link Tuya App Account** (QR постоянно «expired»). Причина —
  **не** таймаут, DC или часы. QR привязан к конкретному приложению, и
  приложения не из allowlist Tuya при скане отклоняются с немедленной
  инвалидацией сессии → страница пишет «QR code has expired». Ваш личный
  Cloud Project в принципе **не может** слинковаться с чужим OEM-приложением
  (Tion Smart) — вкладка Link App Account рассчитана только на Smart Life /
  Tuya Smart. *(Официальная дока Tuya «QR Code-Based Login Authorization»:
  «the app… must be included in the allowlist. Otherwise, an error message is
  returned and the session expires».)*

- **tuya-local / штатная Tuya-интеграция HA, cloud-assisted (user code)**
  («код для другого приложения»). User code проверяется по схеме `haauthorize`,
  под которой зарегистрированы только Smart Life / Tuya Smart. Код из Tion Smart
  ей не соответствует.

Также **точно не помогут** (проверено по исходникам): `tuya-cli --schema`
(это параметр внутри вашего Cloud-проекта, не селектор OEM), `tinytuya wizard`
(работает только через iot.tuya.com), `vineetchoudhary/tuya-local-key`
(schema только smartlife/tuyaSmart), `rospogrigio/localtuya` (нет протокола 3.5).
Ни один форк localtuya не умеет авторизацию через OEM-приложения.

---

## Приёмник (это готово и работает): tuya-local в ручном режиме

Как только `local_key` на руках — локальное подключение делается за минуту,
облако вообще не участвует, Tion Smart не затрагивается.

**Вариант А — [`make-all/tuya-local`](https://github.com/make-all/tuya-local)**
(HACS): Add Integration → Tuya Local → `setup_mode` = **manual** → ввести
`device_id`, host (IP), **local_key**, protocol_version **3.5**.

**Вариант Б — [`xZetsubou/hass-localtuya`](https://github.com/xZetsubou/hass-localtuya)**
(HACS): при добавлении поставить галку **`no_cloud`** → Add device → ввести
host, `device_id`, **local_key**, protocol_version 3.5. Есть поле `manual_dps`
для ручного списка DP.

Проверить связность до настройки HA:
```bash
pip install tinytuya
python -c "import tinytuya,json; d=tinytuya.Device('bf7af32b6fa1a72391lqy6','192.168.254.153','ВАШ_LOCAL_KEY',version=3.5); print(json.dumps(d.status(),indent=2))"
```
Если вернётся `{"dps": {...}}` — ключ верный, дальше вносить в интеграцию.

Готовый device-конфиг 4S (маппинг DP в сущности) —
[tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml).

---

## Как добыть local_key (сохранив Tion Smart)

Все рабочие способы сводятся к одному: **приложение на Tuya SDK хранит
`local_key` у себя** (иначе оно не могло бы управлять устройством по LAN).
Значит его можно прочитать из данных приложения или перехватить при обновлении
списка устройств. Это read-only операция под вашим же аккаунтом — перепарки нет,
Tion Smart продолжает работать.

Нужен **root-Android или Android-эмулятор** (LDPlayer / BlueStacks / Android
Studio AVD с образом без Google Play — там доступен `adb root`). Вход в
Tion Smart на втором устройстве/эмуляторе **не отвязывает** бризер от телефона.

### Способ 1 (рекомендуется) — Frida-скрипт под Tuya SDK

[`redphx/frida-tuya-sdk-debug`](https://github.com/redphx/frida-tuya-sdk-debug) —
снимает SSL-pinning и включает лог Tuya SDK. **Явно поддерживает OEM-приложения**
(в списке — Adaprox Home, тоже white-label Tuya).

1. Эмулятор с root + `frida-server` (версия строго совпадает с `frida-tools`:
   `pip install frida-tools`).
2. Установить Tion Smart, войти в свой аккаунт (Central Europe DC), дождаться
   появления бризера.
3. `frida --no-pause -U -f <пакет_tion_smart> -l debug.js`
   (пакет: `adb shell pm list packages | grep -i tion`).
4. В приложении сделать pull-to-refresh списка устройств → SDK скачает device
   info с `local_key` → всё уйдёт в logcat. Грепать `localKey` / `deviceRespBeen`.

Если глобальный лог не показывает ключ явно —
`frida-trace -j '*!*encodeString*' -p <PID>` и грепать вывод по `local_key`.

### Способ 2 — прочитать файлы кэша устройств

Без MITM. На root-устройстве/эмуляторе с залогиненным Tion Smart:
- **новый формат (вероятен для версии 2026):** бинарный MMKV
  `/data/data/<пакет>/files/thingmmkv/preferences_global_key` — читать через
  библиотеку [Tencent/MMKV](https://github.com/Tencent/MMKV) или `strings`/regex
  по `localKey`;
- **старый формат:** `/data/data/<пакет>/shared_prefs/preferences_global_key<uid>.xml`
  — внутри JSON `deviceRespBeen` с полями `devId`, `localKey`, `productId`.
  Парсер: [`MarkWattTech/TuyaKeyExtractor`](https://github.com/MarkWattTech/TuyaKeyExtractor).

> ⚠️ Не используйте онлайн-сервисы «Tuya Key Extractor Online» — это выгрузка
> ваших учётных данных на чужой сервер.

### Способ 3 — MITM через Frida (если Способ 1 не зашёл)

Ваша прежняя ошибка **«incorrect local timer»** в HTTP Toolkit — это, скорее
всего, **не** непробиваемый pinning, а Tuya-код **50502**: сервер отверг запрос
из-за расхождения часов в подписи. То есть перехват уже прошёл, а помешало
**рассинхронизированное время**. Значит стоит перепроверить:
[`httptoolkit/frida-interception-and-unpinning`](https://github.com/httptoolkit/frida-interception-and-unpinning)
(авто-снятие обфусцированного pinning) **плюс точная NTP-синхронизация** времени
на эмуляторе и на прокси-машине. После снятия pinning `local_key` приходит
открытым текстом в ответе `a1.tuyaeu.com/api.json` (`a=tuya.m.my.group.device.list`).

### Способ 4 (быстрая дешёвая проба, шанс низкий) — tuya-uncover

[`blakadder/tuya-uncover`](https://github.com/blakadder/tuya-uncover) логинится
по email/паролю прямо в облако OEM-приложения и отдаёт `local_key`. В списке
вендоров Tion Smart нет — нужно вытащить `client_id`+`appSecret` из APK
(`apktool d`, meta-data `TUYA_SMART_APPKEY`/`TUYA_SMART_SECRET` в AndroidManifest)
и добавить запись в `_TUYA_KNOWN_VENDORS`, затем `python uncover.py -v tion -r eu <email> "<пароль>"`.

**Риск:** на приложениях новой (ThingClips) эры — а Tion Smart 2026 почти
наверняка такое — часты `SING_VALIDATE_FALED_4`. Стоит попробовать (10 минут),
но не рассчитывать.

---

## Нетехнический путь — запрос в Tion

Включить авторизацию Home Assistant для приложения Tion Smart может **только
владелец OEM-приложения** (Tion), в своей консоли Tuya. Формулировка для их
разработчиков:

> «Приложение Tion Smart построено на Tuya App SDK (OEM App). Просим включить
> для приложения авторизацию Home Assistant по user code / QR (clientid
> `HA_3y9q4ak7g4ephrvke`, schema `haauthorize`) — как это сделано у Smart Life /
> Tuya Smart. Либо выдать `local_key` устройства device_id
> `bf7af32b6fa1a72391lqy6` (product_id `rllylqfcd3lfe3s3`) для локального
> управления по Tuya protocol 3.5.»

Прецедентов, когда OEM-вендор включал это по просьбе пользователей, публично
не найдено — но это единственный путь без reverse-engineering.

---

## Итоговый порядок действий

1. Поднять Android-эмулятор с root, поставить Tion Smart, войти, увидеть бризер.
2. **Способ 2** (прочитать файл кэша) — самый быстрый, если файл не зашифрован.
3. Если зашифрован — **Способ 1** (Frida `redphx/frida-tuya-sdk-debug`).
4. Параллельно, за 10 минут — **Способ 4** (tuya-uncover) как лотерейный билет.
5. Полученный `local_key` → `tinytuya` проверка → **tuya-local manual (3.5)**.
6. Не сработало ничего — **запрос в Tion**.

---

## Данные устройства

| Параметр | Значение |
|---|---|
| product_id | `rllylqfcd3lfe3s3` |
| device_id | `bf7af32b6fa1a72391lqy6` |
| IP | `192.168.254.153` (зарезервировать за MAC в роутере) |
| protocol | 3.5 |
| порт | TCP 6668 |

> `local_key` меняется при каждой перепривязке устройства в приложении —
> после сброса/смены Wi-Fi модуля ключ придётся добыть заново.

## Резервный путь без reverse-engineering

Если возиться с ключом не хочется — облачный мост через Яндекс: бризер уже в
«Доме с Алисой», HACS-компонент
[`AlexxIT/YandexStation`](https://github.com/AlexxIT/YandexStation) импортирует
его в HA (колонка не нужна). Это не локально (лаг ~секунда), но работает сразу.
