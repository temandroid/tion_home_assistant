#!/usr/bin/env python3
"""Отладка авторизации в облаке Tion (расширенная).

ВАЖНО: чтобы пароль точно не пострадал от shell-эскейпа, читаем его из файла.
    echo -n 'мой_пароль' > /tmp/tion_pass
    python debug_auth.py you@mail.com /tmp/tion_pass

Или для разового запуска (если уверены, что shell не съест символы):
    python debug_auth.py you@mail.com --inline 'мой_пароль'

Скрипт пробует разные варианты OAuth-запроса:
  - User-Agent'ы
  - scope'ы (без / openid / magicair / offline_access)
  - client credentials в body vs Basic Authorization header
  - Content-Type variants
"""
import sys
import json
import base64
import requests

CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
CLIENT_SECRET = "syRxSrT77P"
URL = "https://api2.magicair.tion.ru/idsrv/oauth2/token"

SCOPES = [None, "magicair", "openid", "openid offline_access", "openid profile email"]

USER_AGENTS = [
    None,
    "MagicAir/3.0 (Android)",
    "okhttp/4.9.3",
    "MagicAir/1.10.0 (com.tion.magicair; build:1; iOS 17.0.0) Alamofire/5.6.4",
]

CLIENT_AUTH_MODES = ["body", "basic"]


def attempt(email: str, password: str, scope: str | None, ua: str | None, mode: str):
    data = {
        "username": email,
        "password": password,
        "grant_type": "password",
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    if scope is not None:
        data["scope"] = scope
    if ua:
        headers["User-Agent"] = ua

    if mode == "basic":
        token = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    else:  # body
        data["client_id"] = CLIENT_ID
        data["client_secret"] = CLIENT_SECRET

    label = f"scope={scope!r} ua={(ua or 'default')[:30]!r} mode={mode}"
    try:
        r = requests.post(URL, data=data, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"[NET ] {label} -> {e}")
        return False

    if r.status_code == 200:
        print(f"[ OK ] {label}")
        print(f"       body: {r.text[:300]}")
        return True

    short_body = r.text[:200].replace("\n", " ")
    print(f"[{r.status_code:>3}] {label}")
    print(f"       body: {short_body}")
    return False


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    email = sys.argv[1]
    if sys.argv[2] == "--inline":
        if len(sys.argv) < 4:
            print("Usage: ... --inline <password>")
            sys.exit(1)
        password = sys.argv[3]
        print("[!] Пароль из argv — если есть спецсимволы, могло побиться shell'ом.")
    else:
        with open(sys.argv[2], "rb") as f:
            password = f.read().decode("utf-8")
        # уберём финальный \n если файл создан echo без -n
        password = password.rstrip("\r\n")
        print(f"[i] Пароль из файла {sys.argv[2]}, длина={len(password)} байт.")
        print(f"    Первые 2 символа: {password[:2]!r}, последние 2: {password[-2:]!r}")

    print(f"[i] Email: {email!r}")
    print(f"[i] URL: {URL}")
    print(f"[i] client_id: {CLIENT_ID}")
    print()

    success = False
    for scope in SCOPES:
        for ua in USER_AGENTS:
            for mode in CLIENT_AUTH_MODES:
                if attempt(email, password, scope, ua, mode):
                    success = True
                    print("\n=== УСПЕХ ===")
                    print(f"Рабочая комбинация: scope={scope!r}, ua={ua!r}, mode={mode!r}")
                    return

    if not success:
        print("\n=== Все попытки провалились ===")
        print()
        print("Если в приложении MagicAir вход работает теми же кредами —")
        print("значит либо в пароле есть символы, которые искажаются (проверь")
        print("длину выше: совпадает ли с реальной?), либо приложение шлёт")
        print("какие-то дополнительные поля. Следующий шаг — посмотреть HAR")
        print("с веб-кабинета https://magicair.tion.ru (DevTools → Network).")


if __name__ == "__main__":
    main()
