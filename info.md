# Tion Home Assistant

Управление бризерами Tion и датчиками MagicAir в Home Assistant: через облако Tion —
новое (v4, приложение Tion MagicAir, с 1.4.0) или старое MagicAir, пока Tion его не отключил, —
или, для Tion 4S, напрямую по Bluetooth без облака (адаптер хоста или ESPHome Bluetooth proxy).
Настройка через UI.

**Переходите на новое облако так:** сначала обновитесь до 1.4.0 и перезапустите HA,
потом переносите аккаунт в приложении — тогда entity_id и история сохранятся.
Подробности — в README.

Документация: <https://github.com/temandroid/tion_home_assistant>

Бризеры Tion Smart (4S с USB Wi-Fi модулем, 4S TS, Bio X) работают на платформе Tuya,
эта интеграция их не поддерживает. Варианты подключения — в
[docs/tion_smart_wifi.md](https://github.com/temandroid/tion_home_assistant/blob/master/docs/tion_smart_wifi.md).
