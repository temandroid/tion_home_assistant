# Tion Home Assistant

Форк модуля Tion_Home_Assistant от Valeriy Chistyakov (спасибо ему!) с
доработками: config flow (UI-настройка), DataUpdateCoordinator, фиксы по
code-review. История изменений — в [CHANGELOG.md](CHANGELOG.md).

## Какой у вас бризер? Выберите путь

| Ваше устройство | Приложение | Путь |
|---|---|---|
| Бризер + шлюз **MagicAir** (S3/S4/4S/Lite через облако MagicAir) | MagicAir | **Эта интеграция** — см. ниже |
| **4S с USB Wi-Fi модулем** (модуль вышел в фев 2026), **4S TS** | Tion Smart | **[tuya-local (форк old-atstec)](#бризеры-с-wi-fi-tion-smart--tuya)** — UI-настройка, локальное управление |
| **Breezer Bio X** | Tion Smart | tuya-local + ручной YAML — [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md) |

---

## Бризеры с Wi-Fi (Tion Smart / Tuya)

Новые бризеры с Wi-Fi работают через Tuya-стек, а не облако MagicAir — **эта
интеграция для них не подходит**. Зато есть путь целиком через UI, без ручных
YAML-файлов и без developer-аккаунта Tuya:

1. **HACS → Custom repositories** → добавить `old-atstec/tuya-local`
   (Integration) → установить **Tuya Local** → перезапустить HA.
   *Это форк `make-all/tuya-local` с встроенной поддержкой TION Breezer 4S
   (в upstream конфиг не принят).*
2. **Перепарить бризер в приложение Smart Life** (user code от OEM-приложения
   Tion Smart не принимается — схемы аккаунтов разные): удалить устройство в
   Tion Smart → добавить в Smart Life через мастер сопряжения. Затем
   Smart Life → **Settings → Account and Security → User Code** — записать код.
3. **HA → Settings → Devices & Services → Add Integration → Tuya Local** →
   cloud-assisted setup → ввести user code → отсканировать QR приложением
   Smart Life → выбрать бризер. `device_id`/`local_key`/протокол подтянутся
   автоматически, устройство сматчится с конфигом `TION Breezer 4S`.

Управление полностью локальное (Tuya protocol 3.5). Entity'и: climate
(off/heat/fan_only, скорости 1–6, температура), звук/подсветка/рециркуляция,
датчики уличной температуры, мощности нагревателя и ресурса фильтра.

Подробная инструкция, запасные пути (Алиса, штатная Tuya) и troubleshooting:
[docs/tion_smart_wifi.md](docs/tion_smart_wifi.md).

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

### Если что-то не работает

Расширенное логирование в `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.tion: debug
    tion: info
```
