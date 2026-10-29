# Бризеры Tion с Wi-Fi (приложение Tion Smart) → Home Assistant

> Для бризеров на платформе **Tuya** (приложение **Tion Smart**): Tion 4S с
> USB-модулем интеграции Wi-Fi, 4S TS, Bio X. Старые бризеры со шлюзом
> MagicAir — не сюда, для них основная интеграция этого репозитория.

Готовой интеграции «вставь email/пароль от Tion Smart» не существует ни в HACS,
ни на GitHub. Ниже — разбор всех путей: что работает, что закрыто и почему.

---

## Почему стандартные пути закрыты

**Tion Smart — OEM/white-label приложение Tuya.** Аккаунты Tuya живут в
изолированных namespace'ах (app schema), у каждого OEM-приложения свой. Отсюда
все ограничения:

| Путь | Почему не работает |
|---|---|
| `iot.tuya.com` → **Link Tuya App Account** (QR «expired») | Allowlist Tuya: личный Cloud Project линкуется только со Smart Life / Tuya Smart. «QR expired» — это и есть отказ allowlist, а **не** таймаут, DC или часы |
| **user code / cloud-assisted** в штатной Tuya-интеграции и tuya-local | Валидируется по схеме `haauthorize` (клиент `HA_3y9q4ak7g4ephrvke`) — под ней только Smart Life / Tuya Smart |
| Легаси `px1.tuya*.com/homeassistant/auth.do` + `bizType` | Endpoint **жив** (проверено 04.08.2026), но `bizType` — серверный белый список: только `tuya`, `smart_life`, `jinvoo_smart`. Прямое свидетельство отказа для OEM-бренда: `ndg63276/smartathome#12` → `platform geeni not support!`. Библиотеки `tuyaha`/`ha_tuya_custom` заархивированы в 2021 |
| Alexa / Google Home как мост | Привязать можно, но обратно устройства не отдаются — пользовательского API «выгрузи мой дом» у них нет |
| Кросс-app шеринг Tion Smart → Smart Life | Данные приложений Tuya независимы; плюс `core#117048` — расшаренные устройства штатная интеграция не подхватывает |
| `tuya-uncover` «из коробки» | Умеет **только чтение**, Tion в списке вендоров нет, `-v generic` не запустится без правки argparse |

### Как Алиса это обходит

Навык Smart Life в Алисе — это **cloud-to-cloud account linking по OAuth 2.0**
с **партнёрским** `client_id`, выданным Tuya Яндексу по контракту. Список
white-label приложений по email показывает серверная логика H5-страницы
авторизации Tuya: партнёрский клиент имеет право перечислить namespace'ы, где
этот email зарегистрирован.

**Публичного endpoint «дай список OEM-приложений по email» не существует** — это
внутренний вызов, доступный только партнёрскому клиенту. Повторить именно этот
механизм энтузиасту нельзя.

---

## Путь 1 — эмуляция мобильного приложения (единственный прямой)

Работает **и для облачного, и для локального** управления. Не требует ни Cloud
Project, ни партнёрства: вход по обычному email+паролю аккаунта Tion Smart.

```
POST https://a1.tuyaeu.com/api.json
```

Endpoint жив (проверено 04.08.2026: мусорный clientId → `ILLEGAL_CLIENT_ID`,
реальный clientId с неверной подписью → `SING_VALIDATE_FALED_4`).
Управление — action `tuya.m.device.dp.publish` с телом `{devId, gwId, dps:{...}}`;
облачная запись подтверждена в живом коде [`Apollon77/ioBroker.tuya`](https://github.com/Apollon77/ioBroker.tuya)
(`lib/appcloud.js`, метод `set()`, push 30.06.2026) и `jnicolaes/eufy-robomow-ha`.

**Цена входа — вытащить из APK Tion Smart секреты приложения и воспроизвести
его подпись.** Это единственный шаг, который может провалиться целиком.

### Что нужно достать

Окружение: рутованный Android-эмулятор (Android Studio AVD с образом без
Google Play → `adb root`, либо LDPlayer), Tion Smart (`com.tion.tionsmart`),
вход в свой аккаунт, бризер виден в списке.

| Секрет | Где искать | Сложность |
|---|---|---|
| `appKey` (clientId, 20 симв.) и `appSecret` (32 симв.) | `jadx-gui`/`apktool d`, грепать `clientId`, `initKey`, `appKey`, `TUYA_SMART_APPKEY`, `THING_SMART_*`, `strings.xml`, `BuildConfig` | обычно минуты |
| `certSign` | для OEM-сборок исторически литерал `'A'`; иначе SHA-256 подписного сертификата (`openssl pkcs7 … CERT.RSA`) | минуты |
| `secret2` (BMP-токен) | стеганография в `assets/t_s.bmp`, декодер [`nalajcie/tuya-sign-hacking`](https://github.com/nalajcie/tuya-sign-hacking) | **основная работа** |

⚠️ Декодер BMP валидирован только на TuyaSmart v3.8.0 (2019). Tion Smart собран
на свежем SDK (ThingClips, `com.thingclips.*`, `libthing_security.so`) — скорее
всего старый декодер не ляжет, и токен придётся снимать **Frida-хуком нативной
функции подписи** ([`redphx/frida-tuya-sdk-debug`](https://github.com/redphx/frida-tuya-sdk-debug)).

### Схема подписи

В 2026 сосуществуют минимум две — какая у Tion Smart, **не подтверждено**,
определять эмпирически по APK:

- **Старая:** `sign = HMAC-SHA256(key = "<certSign>_<secret2>_<appSecret>", strToSign)`.
  Референс: `TuyaAPI/cloud/index.js`, `blakadder/tuya-uncover/uncover.py`.
- **Новая (SDK 6.x / ThingClips):** ключ из четырёх частей, `postData` шифруется
  **AES-128-GCM**, параметр `et=3`, заголовок `Thing-UA`. Готовая реализация:
  `errrrata/hacs-inkbird-wifi` → `custom_components/inkbird_wifi/tuya_cloud.py`.

Логин: старый флоу `tuya.m.user.email.token.create` → `tuya.m.user.email.password.login`;
новый — `thing.m.user.username.token.get` → `thing.m.user.email.password.login`
(может вернуть `MFA_NEED_SEND_CODE`). Проверка: `tuya.m.my.group.device.list`.

### Карта DP уже есть

Маппинг для 4S — в [tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml):

| DP | Назначение |
|---|---|
| 1 | питание (bool) |
| 108 | скорость 1..6 |
| 109 | целевая температура 0..25 |
| 112 | `Recirc` / `Inflow` |
| 102 / 101 | звук / подсветка |
| 9 / 10 | текущая / наружная температура |
| 104 / 105 | мощность нагрева / ресурс фильтра |
| 111 / 113 | hvac_action / неисправность |

### Трудозатраты

| Сценарий | Время |
|---|---|
| Оптимистичный (старая схема, секреты грепаются) | 1–2 вечера |
| Реалистичный (ThingClips, Frida-хук, AES-GCM) | **2–5 вечеров** при опыте с apktool/Frida |
| Без опыта Android-реверса | больше, с риском не закрыть шаг с секретами |

> **Важная страховка:** подготовка для облачного и локального пути **одинаковая**
> (рутованный эмулятор + Tion Smart). Но локальному нужен **один** секрет
> (`local_key`), прочитанный один раз, а облачному — воспроизвести всю схему
> подписи и гонять её на каждый запрос. Если Frida-лог отдаст `localKey`, но
> подпись снять не выйдет — останется рабочее локальное решение
> (tuya-local, protocol 3.5). То есть шаг не «всё или ничего».

---

## Путь 2 — официальный API Яндекса (предсказуемый по срокам)

Бризер уже привязан к Яндексу через навык Smart Life. Вместо приватного API
Квазара использовать документированный публичный
[`api.iot.yandex.net`](https://yandex.ru/dev/dialogs/smart-home/doc/reference-alice/get-devices.html) —
он отдаёт устройства собственного умного дома, включая подключённые сторонними
навыками.

Регистрация приложения на `oauth.yandex.ru` → OAuth-токен →
`GET /v1.0/user/info` (конфигурация), `GET /v1.0/devices/{id}` (состояние),
`POST` для команд.

**Плюс:** легально, стабильно, не сломается от смены приватного API.
**Минус:** только polling — изменения с панели бризера приедут с задержкой опроса.
Трудозатраты: один-два вечера, риск близок к нулю.

---

## Путь 3 — оставить как есть (AlexxIT/YandexStation)

Работает сейчас, обновления идут по **WebSocket** приватного API Квазара и
приходят практически мгновенно — включая управление с самой панели бризера.

**Минус:** приватный API, Яндекс его ломал (в v3.21.0 от 15.05.2026 авторизация
полностью переписана; рабочие способы — QR, cookies, перенос токена).

---

## Путь 4 — локально через local_key (самый практичный при наличии Android Studio)

Если удалённый доступ не критичен: добыть `local_key` рутованным эмулятором
(нужен только **один** секрет, а не вся схема подписи) → `make-all/tuya-local`
в режиме **manual** или `xZetsubou/hass-localtuya` с галкой **`no_cloud`**:
device_id, IP, local_key, protocol **3.5**.

**Пошаговая инструкция под Android Studio:** [extract_local_key.md](./extract_local_key.md).

Проверка ключа до настройки HA:
```bash
pip install tinytuya
python -c "import tinytuya,json; d=tinytuya.Device('DEVICE_ID','IP','LOCAL_KEY',version=3.5); print(json.dumps(d.status(),indent=2))"
```

---

## Путь 5 — запрос в Tion (нетехнический)

Включить авторизацию Home Assistant для приложения может **только владелец
OEM-приложения** в своей консоли Tuya:

> «Приложение Tion Smart построено на Tuya App SDK (OEM App). Просим включить
> для приложения авторизацию Home Assistant по user code / QR (clientid
> `HA_3y9q4ak7g4ephrvke`, schema `haauthorize`) — как это сделано у Smart Life /
> Tuya Smart.»

Публичных прецедентов, когда OEM-вендор это включал по просьбе пользователей,
не найдено.

---

## Дешёвые пробы перед реверсом (~1 час)

1. **User Code и сканер в Tion Smart** (5 мин). Профиль → Настройки → Аккаунт и
   безопасность → есть ли «User Code»; есть ли сканер QR. Если обоих нет — путь
   через user code закрыт окончательно.
2. **Своя schema** (20 мин, если User Code есть). Эксперимент 04.08.2026 показал:
   endpoint `apigw.iotbing.com/v1.0/m/life/home-assistant/qrcode/tokens` принимает
   **произвольные** строки в `schema` — валидация происходит позже, на стороне
   сканирующего приложения. Подменить `TUYA_SCHEMA` в `custom_components/tuya_local/const.py`
   на кандидаты (`tionsmart`, `tion`, `tion_smart`), перезапустить HA, отсканировать
   QR в Tion Smart. Строка schema для Tion **не подтверждена** — это угадывание,
   шанс низкий, но проверка дешёвая.
3. **Шеринг в Smart Life** (5 мин). Tion Smart → устройство → Общий доступ →
   добавить аккаунт Smart Life. Ожидание — отказ.

---

## Данные устройства

| Параметр | Значение |
|---|---|
| product_id | `rllylqfcd3lfe3s3` |
| protocol | 3.5 |
| порт (локально) | TCP 6668 |
| DC аккаунта | Central Europe → `a1.tuyaeu.com` |
| пакет приложения | `com.tion.tionsmart` |

Готовых решений под Tion Smart в мире нет: поиск кода по GitHub на
`com.tion.tionsmart` — 0 результатов, в списке ~41 вендора `tuya-uncover` его нет.

---

## Ревизия 2026-10-29 — что изменилось с августа 2026

Повторная проверка (веб, GitHub, форумы HA/Tuya) перед принятием решения.
**Короткий вердикт: ничего не открылось.** Прямой путь HA → облако Tion Smart
по-прежнему закрыт ровно теми же стенами, что и в августе; появившиеся за это
время инструменты лишь **подтверждают** закрытие для OEM-приложений.

### По-прежнему закрыто (подтверждено заново)

| Что | Статус на 2026-10-29 | Источник |
|---|---|---|
| OEM-аккаунт = отдельный namespace | Без изменений. Официальный FAQ Tuya: аккаунты OEM-приложения — **отдельная система**, не логинятся в Smart Life / Tuya Smart даже с тем же логином/паролем | [support.tuya.com — OEM accounts](https://support.tuya.com/en/help/_detail/K93eolrqjoiu7) |
| `haauthorize` / user code для OEM | Без изменений. Штатная Tuya-интеграция HA и `tuya-device-sharing-sdk` построены вокруг QR Smart Life / Tuya Smart; ввода логина/пароля OEM-аккаунта нет | [HA Tuya integration](https://www.home-assistant.io/integrations/tuya/) |
| QR-логин как источник `local_key` | **Новый инструмент, но для OEM не работает.** `vineetchoudhary/tuya-local-key` (v3.0, 02.10.2026) достаёт `local_key` по QR **без** IoT-проекта — но автор прямо пишет: только Smart Life / Tuya Smart, vendor-branded приложения (а это Tion Smart) не поддерживаются, поля логин/пароль нет | [HA Community — tuya-local-key](https://community.home-assistant.io/t/get-tuya-local-key-via-smartlife-tuyasmart-qr-login-no-tuya-iot-developer-account/1018805) |
| Smart Life HA integration для OEM | Без изменений; локального управления всё ещё нет, миграция с Tuya v2 невозможна | [tuya/tuya-home-assistant](https://github.com/tuya/tuya-home-assistant) |
| Готовое решение под Tion Smart | Нет. Поиск по GitHub на `com.tion.tionsmart` и product_id `rllylqfcd3lfe3s3` — по-прежнему 0 проектов | веб-поиск 29.10.2026 |
| Tion 4S в upstream `tuya-local` | Не добавлен. Поддержка устройств community-driven, свежие релизы `make-all/tuya-local` (2026.5.4) Tion не содержат; наш `tion_breezer_4s_tuya_local.yaml` остаётся единственной картой DP | [make-all/tuya-local releases](https://github.com/make-all/tuya-local/releases) |

### Новое, но мимо цели

- **Новое облако Tion (v4) для MagicAir-экосистемы.** С октября 2026 community-интеграция
  `vaproloff/tion_home_assistant` (релиз 2026.10.0) перешла на «новое облако Tion»;
  старое облако отключается, аккаунт переносится в приложении Tion MagicAir.
  🔸 *Низкая уверенность по связи с нашим кейсом:* это ветка **MagicAir**, не Tuya.
  Про 4S с USB Wi-Fi и Tion Smart в релизе — ни слова; **нет свидетельств**, что
  Wi-Fi-бризер теперь виден в облаке MagicAir. Две экосистемы (MagicAir vs
  Tion Smart/Tuya) остаются раздельными.
  [vaproloff release 2026.10.0](https://github.com/vaproloff/tion_home_assistant/releases/tag/2026.10.0) ·
  [PR #40 «Переход на новое облако (v4)»](https://github.com/vaproloff/tion_home_assistant/pull/40)
  ⚠️ **Побочно важно для нашего репо:** наш облачный режим ходит в `magicair.tion.ru`
  через pypi-`tion`. Если старое облако MagicAir гасят — облачный режим этой
  интеграции под угрозой и, вероятно, тоже потребует перевода аккаунта + обновления
  апстрим-пакета. Это отдельный вопрос, не про Wi-Fi-путь. *(Средняя уверенность.)*
- **Tion ужесточает свою облачную авторизацию.** В `vaproloff#42` (октябрь 2026)
  вход ломается на капче: Tion стал принимать только токен капчи, решённый на
  localhost-странице. Вывод для нас: любой сторонний облачный клиент к Tion
  становится более хрупким — это довод против облачных мостов в принципе.
  [vaproloff issue #42](https://github.com/vaproloff/tion_home_assistant/issues/42)
- **Официальный Tion:** открытого API, Matter для 4S или штатной HA-интеграции
  по-прежнему не найдено. *(Отсутствие подтверждения, не доказательство отсутствия.)*

### Вердикт и следующий шаг (без изменений с августа)

Прямого «вставь email/пароль Tion Smart» не появилось и не предвидится: барьер
архитектурный (изолированный namespace OEM + allowlist на `haauthorize`), а не
временный баг. Единственный прямой облачный путь — тот же **Путь 1**: эмуляция
мобильного приложения против `a1.tuyaeu.com/api.json` с реверсом секретов из APK.

**Рекомендуемый следующий шаг — по приоритету цели:**
1. Если удалённый доступ НЕ критичен → **локальный `local_key`** (рутованный
   эмулятор → `tuya-local` manual / `hass-localtuya` no_cloud, protocol 3.5):
   один секрет, минимальный риск, карта DP готова. См. [extract_local_key.md](./extract_local_key.md).
2. Если облако обязательно → реверс APK (Путь 1). Схема подписи Tion Smart
   по-прежнему **не подтверждена** — определять эмпирически.

Новых «дешёвых проб» не добавилось; проверки из раздела выше остаются актуальными.
