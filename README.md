# ВНИМАНИЕ!!!
Это fork (доработанная копия) оригинального модуля Tion_Home_Assistant от Уважаемого Valeriy Chistyakov.
Большое спасибо ему за модуль, я только поправил кое-какие замечания по синтаксису, которые вылезли после обновления Home Assistant до версии 2024.01

# Tion Home Assistant
Интеграция обеспечивает управление бризерами Tion, а также чтение показаний датчиков (включая датчики MagicAir) из системы умного дома Home Assistant. Основано на пакете [tion](https://github.com/airens/tion).

*Внимание: для работы требуется шлюз MagicAir!*

> **Для бризеров с Wi-Fi через приложение Tion Smart эта интеграция НЕ подходит.**
> Это касается Tion 4S с USB-модулем Wi-Fi (вышел в фев 2026), 4S TS со встроенным
> модулем, а также Breezer Bio X. Они используют Tuya-стек, а не MagicAir.
> Рекомендуемый путь сейчас — **через навык Smart Life в Алисе + HACS-интеграция Yandex → HA**.
> Подробнее: [docs/tion_smart_wifi.md](docs/tion_smart_wifi.md). Альтернативный путь через
> локальный канал (`tuya-local`) пока в проработке — нужно решить вопрос с `local_key`.
## Установка
### HACS:
1. HACS->Settings->Custom repositories 
2. Добавьте `RealLord/tion_home_assistant` в поле `ADD CUSTOM REPOSITORY` и выберите `Integration` в `CATEGORY`. Щелкните кнопку `Save`
### Без HACS:
1. скачайте zip файл с компонентом
2. поместите содержимое в `config/custom_components/tion` папку системы Home Assistant
### Настройка (v1.2.0+)
Начиная с версии 1.2.0 интеграция настраивается через UI:

1. Перезагрузите Home Assistant
2. `Settings → Devices & Services → Add Integration → Tion`
3. Введите email/пароль от облака MagicAir — будет произведена проверка

Опции (период опроса, путь к файлу авторизации) меняются через кнопку **Configure** у интеграции.

### Backward-compat: YAML
Старый блок `tion:` в `configuration.yaml` всё ещё работает — при старте HA он автоматически импортируется в config entry (с deprecation-warning). После успешного импорта рекомендуется удалить YAML-секцию.

```yaml
# DEPRECATED — будет автоматически импортировано в UI
tion:
  username: !secret tion_email
  password: !secret tion_password
  scan_interval: 600
  file_path: "/tmp/tion_auth"
```
## Использование:
После перезагрузки, среди устройств должны появиться бризеры `climate.tion_...` и датчики MagicAir `sensor.magicair_..`.

Службы Home Assistant для управления вашими устройствами:
### climate.set_fan_mode
`fan_mode` задает скорость бризера следующим образом (тип - строка):
- `off`, `0` - выключить
- `1`-`6` - включить в ручном режиме с заданной скоростью
- `auto` - автоматическое управление скоростью в зависимости от уровня CO2
  - определяется переменной target_co2 (изменить можно только через PRESET)
### climate.set_hvac_mode
`hvac_mode` задает режим работы прибора:
- `heat` - нагреватель включен
- `fan_only` - нагреватель выключен
- `off` - прибор выключен
### climate.set_temperature
Используйте для задачи целевой температуры нагревателя
### climate.set_swing
Используйте для задания источника потока воздуха: улица, квартира, смешанный
- SWING_VERTICAL = воздух из квартиры
- SWING_BOTH = смешанный
- SWING_HORIZONTAL = воздух с улицы
### climate.set_preset
Используйте для задания заранее запрограммированных настроек (пресетов)
- PRESET_SLEEP:    с улицы,     скорость 1, обогреватель выключен
- PRESET_ACTIVITY: с улицы,     скорость 2, обогреватель выключен
- PRESET_BOOST:    с улицы,     скорость 6, обогреватель выключен
- PRESET_HOME:     из квартиры, скорость 2, обогреватель выключен           
- PRESET_COMFORT:  смешанный,   скорость 3, обогреватель выключен 
- PRESET_AWAY: Режим AUTO, target_c02 = 600, с улицы, скорость 1-6, обогреватель выключен
- PRESET_ECO:  Режим AUTO, target_c02 = 700, с улицы, скорость 1-4, обогреватель выключен

## Если что-то не работает
Включите расширенное логирование для интеграции и пакета `tion` в файле конфигурации `configuration.yaml`:
```yaml
logger:
  default: warning
  logs:
    custom_components.tion: info
    tion: info
```
