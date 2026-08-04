# Извлечение local_key через Android Studio (пошагово)

> Цель: получить `local_key` бризера Tion 4S, чтобы управлять им **локально** из
> Home Assistant через tuya-local, не ломая приложение Tion Smart.
> Приёмник уже готов — [tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml).
>
> Всё легально: своё устройство, свой аккаунт, свои данные. Онлайн-сервисы
> «Tuya Key Extractor» НЕ использовать — это выгрузка учётных данных на чужой сервер.

Локальный порт бризера (TCP 6668) уже открыт, `tinytuya scan` его видит.
Не хватает только ключа.

---

## Шаг 1. Создать эмулятор с root (критично!)

В Android Studio → Device Manager → Create Virtual Device:

- Любой телефон (Pixel 6 и т.п.)
- System Image: **обязательно «Google APIs», НЕ «Google Play»**
  (архитектура x86_64, API 30–34). Только образ без Play Store даёт `adb root` —
  без него до данных приложения не добраться.

Запустить эмулятор, проверить root в терминале:
```bash
adb root
```
Должно ответить `restarting adbd as root` (или `adbd is already running as root`).
Если пишет `adbd cannot run as root in production builds` — выбран неверный образ,
пересоздать с «Google APIs».

## Шаг 2. Установить Tion Smart в эмулятор

В образе без Play Store магазина нет — ставим APK вручную.

1. Скачать APK Tion Smart (пакет `com.tion.tionsmart`) из **RuStore**, APKMirror
   или APKPure. Если скачался `.xapk`/`.apks` (split) — распаковать (это zip) и
   ставить `adb install-multiple *.apk`; если обычный `.apk` — просто:
   ```bash
   adb install tion-smart.apk
   ```
2. Открыть приложение в эмуляторе, **войти в свой аккаунт** (регион — Europe,
   тот же, что на телефоне). Вход на втором устройстве **не отвязывает** бризер
   от телефона и **не меняет** `local_key`.
3. Дождаться появления бризера в списке, сделать **pull-to-refresh** — приложение
   скачает данные устройств с ключами в локальный кэш.

## Шаг 3. Достать local_key из кэша приложения

```bash
adb root
adb shell ls -la /data/data/com.tion.tionsmart/shared_prefs/
adb shell ls -la /data/data/com.tion.tionsmart/files/thingmmkv/
```

Ключ лежит в одном из двух форматов:

**Старый (XML):** файл `shared_prefs/preferences_global_key<цифры>.xml`
(брать наибольший по размеру). Вытащить и открыть:
```bash
adb pull /data/data/com.tion.tionsmart/shared_prefs/preferences_global_key123.xml
```
Внутри `<string>` — HTML-экранированный JSON с массивом `deviceRespBeen`, где у
каждого устройства есть `devId`, `localKey`, `productId`. Найти запись с
`devId = bf7af32b6fa1a72391lqy6` → скопировать `localKey`.

**Новый (MMKV, вероятен для сборки 2026):** бинарный файл
`files/thingmmkv/preferences_global_key`. Вытащить и грепнуть:
```bash
adb pull /data/data/com.tion.tionsmart/files/thingmmkv/preferences_global_key
strings preferences_global_key | grep -i localkey
```
Если `strings` не показал ключ (значение зашифровано) — см. Шаг 3b.

### Шаг 3b (запасной) — если файл зашифрован: Frida

MMKV в свежих SDK может быть зашифрован ключом приложения. Тогда читать
значение в рантайме:

1. Поставить `frida-server` в эмулятор (версия строго совпадает с `frida-tools`:
   `pip install frida-tools`), запустить.
2. Использовать [`redphx/frida-tuya-sdk-debug`](https://github.com/redphx/frida-tuya-sdk-debug)
   (снимает pinning + логирует Tuya SDK, **явно поддерживает OEM-приложения**):
   ```bash
   frida --no-pause -U -f com.tion.tionsmart -l debug.js
   ```
3. В приложении — pull-to-refresh списка. `localKey` появится в logcat/выводе.
   Либо точечно: `frida-trace -j '*!*encodeString*' -p <PID>` и грепать по `local_key`.

## Шаг 4. Проверить ключ

```bash
pip install tinytuya
python -c "import tinytuya,json; d=tinytuya.Device('bf7af32b6fa1a72391lqy6','192.168.254.153','ВАШ_LOCAL_KEY',version=3.5); print(json.dumps(d.status(),indent=2))"
```
Вернулся `{"dps": {"1": ..., "108": ...}}` — ключ верный, идём в HA.
`Invalid key` / таймаут — перепроверить ключ и что Tion Smart на телефоне
не держит эксклюзивную сессию (закрыть приложение на телефоне на время теста).

## Шаг 5. Подключить в Home Assistant

HACS → [`make-all/tuya-local`](https://github.com/make-all/tuya-local) →
Add Integration → Tuya Local → `setup_mode` = **manual**:

| Поле | Значение |
|---|---|
| device_id | `bf7af32b6fa1a72391lqy6` |
| host | `192.168.254.153` |
| local_key | из шага 3 |
| protocol_version | **3.5** |

Положить [tion_breezer_4s_tuya_local.yaml](./tion_breezer_4s_tuya_local.yaml) в
`<HA config>/custom_components/tuya_local/devices/tion_breezer_4s.yaml` —
устройство сматчится по product_id, появятся сущности climate, switch, sensor.

---

## Развилки и подводные камни

| Ситуация | Что делать |
|---|---|
| `adb root` не работает | Пересоздать AVD с образом **Google APIs**, не Google Play |
| APK — split (`.apks`/`.xapk`) | Распаковать zip, `adb install-multiple *.apk` |
| `preferences_global_key*` не найден | Проверить точное имя пакета: `adb shell pm list packages \| grep -i tion` |
| MMKV зашифрован (`strings` пусто) | Шаг 3b — Frida |
| В HA сущности есть, но не реагируют | Tuya держит одну локальную сессию — закрыть Tion Smart на телефоне |
| `local_key` перестал работать позже | Меняется при перепарке устройства (сброс + заново в приложении) — достать заново |

## Заодно: если решишь делать облачный путь

В том же распакованном APK (`jadx-gui`/`apktool d`) можно сразу глянуть
`appKey`/`appSecret` (грепать `clientId`, `TUYA_SMART_APPKEY`, `strings.xml`) и
app schema (deep-link в `AndroidManifest.xml`) — они нужны для облачной эмуляции
приложения (см. [tion_smart_wifi.md](./tion_smart_wifi.md), Путь 1). Но для
локального управления они не требуются — хватает `local_key`.
