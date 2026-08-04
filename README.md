# Tion Home Assistant

Форк модуля Tion_Home_Assistant от Valeriy Chistyakov (спасибо ему!) с
доработками: config flow (UI-настройка), DataUpdateCoordinator, фиксы по
code-review. История изменений — в [CHANGELOG.md](CHANGELOG.md).

## Какой у вас бризер? Выберите путь

| Ваше устройство | Приложение | Путь |
|---|---|---|
| Бризер + шлюз **MagicAir** (S3/S4/4S/Lite через облако MagicAir) | MagicAir | **Эта интеграция** — см. ниже |
| **4S с USB Wi-Fi модулем** / **4S TS** — нужно **локально**, приложение сохранить | Tion Smart | **BLE через ESP32** ([esphome-tion](https://github.com/dentra/esphome-tion)) — [docs/local_control.md](docs/local_control.md) |
| Ворота/роллеты **ALUTECH** — нужно **локально**, приложение сохранить | ALUTECH Smart | **Shelly на сухих контактах** — [docs/local_control.md](docs/local_control.md) |
| То же, но проще и можно через облако | Tion Smart / ALUTECH Smart | Алиса → HA (AlexxIT/YandexStation) — [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md) |
| **Bio X** | Tion Smart | Tuya-пути — [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md) |

---

## Бризеры с Wi-Fi (Tion Smart) и ворота ALUTECH Smart

Новые бризеры Tion и автоматика ALUTECH работают на Tuya-платформе — **эта
интеграция для них не подходит**. Выбор пути зависит от одного вопроса:
**должно ли продолжать работать родное приложение?**

**Локально + родное приложение работает** (рекомендуется) — заходить не через
Tuya, а по второму, независимому каналу управления:
- **Tion 4S** — по **BLE** через ESP32 и [`dentra/esphome-tion`](https://github.com/dentra/esphome-tion).
  Wi-Fi модуль не трогаем, Tion Smart работает параллельно.
- **Ворота ALUTECH** — реле **Shelly** на клеммы внешней кнопки привода.
  Zigbee-хаб и приложение ALUTECH Smart не затрагиваются.

Подробности: **[docs/local_control.md](docs/local_control.md)**.

**Проще, но через облако** — привязать устройства к «Дому с Алисой» через навыки
их приложений и импортировать в HA компонентом
[`AlexxIT/YandexStation`](https://github.com/AlexxIT/YandexStation) (колонка не
обязательна). Tuya-пути и Bio X: [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md).

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
