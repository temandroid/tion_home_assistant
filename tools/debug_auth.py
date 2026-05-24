#!/usr/bin/env python3
"""Отладка авторизации в облаке Tion.

Использование:
    pip install requests
    python debug_auth.py you@mail.com 'your_password'

Скрипт делает ровно то же, что пакет `tion`, но:
  - печатает HTTP-статус и тело ответа
  - пробует несколько User-Agent (мобильное приложение vs дефолтный requests)
  - пробует альтернативные endpoint'ы (api2 vs api3)
  - подсказывает по коду ошибки

Если все попытки 400/invalid_client — нужно перехватить запрос актуального
мобильного приложения MagicAir (HTTP Toolkit / mitmproxy) и достать новый
client_id/secret.
"""
import sys
import json
import requests

# Из tion 1.28
CLIENT_ID_LEGACY = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
CLIENT_SECRET_LEGACY = "syRxSrT77P"

ENDPOINTS = [
    "https://api2.magicair.tion.ru/idsrv/oauth2/token",
    "https://api3.magicair.tion.ru/idsrv/oauth2/token",
    "https://api.magicair.tion.ru/idsrv/oauth2/token",
]

USER_AGENTS = [
    ("default-requests", None),
    ("magicair-android", "MagicAir/3.0 (Android)"),
    ("magicair-ios", "MagicAir/3.0 (iOS)"),
    ("okhttp", "okhttp/4.9.3"),
]


def try_auth(email: str, password: str, url: str, ua: str | None):
    data = {
        "username": email,
        "password": password,
        "client_id": CLIENT_ID_LEGACY,
        "client_secret": CLIENT_SECRET_LEGACY,
        "grant_type": "password",
    }
    headers = {}
    if ua:
        headers["User-Agent"] = ua

    print(f"\n>>> POST {url}")
    print(f"    User-Agent: {ua or '(default)'}")
    try:
        r = requests.post(url, data=data, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"    NETWORK ERROR: {e}")
        return None

    print(f"    status: {r.status_code}")
    print(f"    headers: {dict(r.headers)}")
    body = r.text[:1500]
    print(f"    body: {body}")

    if r.status_code == 200:
        try:
            js = r.json()
            print(f"    >>> SUCCESS! token_type={js.get('token_type')}, expires_in={js.get('expires_in')}")
            return js
        except Exception as e:
            print(f"    !!! 200 OK но не JSON: {e}")
            return None

    # подсказки
    try:
        err = r.json()
        code = err.get("error") or err.get("Message") or err.get("error_description")
        hint = {
            "invalid_client": "Облако сменило client_id/secret. Нужно перехватить запрос актуального мобильного приложения.",
            "invalid_grant": "Логин/пароль не приняты, либо grant_type 'password' депрекейтнут (см. PKCE).",
            "unsupported_grant_type": "Перешли на code-flow с PKCE. Нужно переписывать auth полностью.",
            "invalid_request": "Сменился формат запроса (поля отличаются).",
            "unauthorized_client": "client_id заблокирован для этого grant_type.",
        }.get(code, "")
        if hint:
            print(f"    >>> Подсказка: {hint}")
    except Exception:
        if "<html" in body.lower():
            print("    >>> Подсказка: вернулся HTML (вероятно Cloudflare/captcha). Попробовать User-Agent мобильного приложения.")

    return None


def main():
    if len(sys.argv) != 3:
        print("Usage: python debug_auth.py <email> <password>")
        sys.exit(1)
    email, password = sys.argv[1], sys.argv[2]

    print(f"Тест авторизации Tion для {email!r}")
    print(f"client_id (legacy): {CLIENT_ID_LEGACY}")

    for url in ENDPOINTS:
        for ua_name, ua in USER_AGENTS:
            result = try_auth(email, password, url, ua)
            if result:
                print("\n=== Успех ===")
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return

    print("\n=== Все попытки провалились ===")
    print("Следующие шаги:")
    print("  1. Поставь HTTP Toolkit (https://httptoolkit.com/) на телефон.")
    print("  2. Открой приложение MagicAir, залогинься.")
    print("  3. Скопируй POST-запрос на endpoint вида /idsrv/oauth2/token (или новый).")
    print("  4. Вставь актуальные client_id/secret/URL в этот скрипт и проверь.")


if __name__ == "__main__":
    main()
