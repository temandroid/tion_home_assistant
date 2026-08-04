# Tion Home Assistant

Форк модуля Tion_Home_Assistant от Valeriy Chistyakov (спасибо ему!) с
доработками: config flow (UI-настройка), DataUpdateCoordinator, фиксы по
code-review. История изменений — в [CHANGELOG.md](CHANGELOG.md).

## Какой у вас бризер? Выберите путь

| Ваше устройство | Приложение | Путь |
|---|---|---|
| Бризер + шлюз **MagicAir** (S3/S4/4S/Lite через облако MagicAir) | MagicAir | **Эта интеграция** — см. ниже |
| **4S с USB Wi-Fi модулем**, **4S TS**, **Bio X** — родное приложение должно работать | Tion Smart | **Алиса → HA** (AlexxIT/YandexStation) или local_key через iot.tuya.com — [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md) |
| То же, но родное приложение не нужно | Tion Smart | Перепарка в Smart Life + tuya-local (форк old-atstec) — полностью локально, всё через UI |
| Ворота/роллеты **ALUTECH Smart** (тоже Tuya) | ALUTECH Smart | Те же пути, что для Tion Smart — [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md) |

---

## Бризеры с Wi-Fi (Tion Smart) и ворота ALUTECH Smart

Новые бризеры Tion и автоматика ALUTECH работают на Tuya-платформе — **эта
интеграция для них не подходит**. Выбор пути зависит от одного вопроса:
**должно ли продолжать работать родное приложение?**

- **Да, родное приложение нужно** → мост через Алису: устройства привязываются
  к «Дому с Алисой» через навыки своих приложений, HACS-компонент
  [`AlexxIT/YandexStation`](https://github.com/AlexxIT/YandexStation) импортирует
  их в HA (колонка не обязательна). Либо, для локального управления —
  local_key через developer-проект iot.tuya.com (OEM-аккаунт привязывается
  read-only, устройства из приложений не пропадают).
- **Нет, не нужно** → перепарка в Smart Life + форк `old-atstec/tuya-local`:
  полностью локально, вся настройка через UI.

Пошаговые инструкции по всем трём путям и troubleshooting:
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
