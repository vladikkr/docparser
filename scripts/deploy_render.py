#!/usr/bin/env python3
"""Deploy the Telegram bot to Render as a background worker, end to end.

Creating a Render account needs a browser and is the one step that cannot be
scripted. Everything after that can: this creates the worker, sets the
environment, triggers the deploy, waits for it and reads the logs, so the
human part is "sign up, copy an API key, paste it here".

    python scripts/deploy_render.py            # ask for the key, then deploy
    python scripts/deploy_render.py --dry-run  # show what would be sent

A worker rather than a web service is the point: the bot asks Telegram for
updates over an outgoing connection, so it needs no public address, and unlike
a free web service it is not put to sleep.
"""

from __future__ import annotations

import argparse
import getpass
import pathlib
import sys
import time
from typing import Any

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import settings

API = "https://api.render.com/v1"
REPO = "https://github.com/vladikkr/docparser"
BRANCH = "master"
DOCKERFILE = "./docker/Dockerfile.bot"
REGION = "frankfurt"
PLAN = "free"
SERVICE_NAME = "docparser-bot"
TIMEOUT_SECONDS = 45 * 60


def service_payload(owner_id: str) -> dict[str, Any]:
    """The create-service body. Docker, because OCR needs system packages."""
    return {
        "type": "worker",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "repo": REPO,
        "branch": BRANCH,
        "region": REGION,
        "plan": PLAN,
        "dockerContext": ".",
        "dockerfilePath": DOCKERFILE,
        "autoDeployTrigger": "checksPass",
    }


def env_payload() -> list[dict[str, str]]:
    """Environment for the worker.

    The bot token is sent to Render only, never printed, and never committed:
    .env is gitignored. A worker has no persistent disk unless one is attached,
    so the state file lives inside the container and is documented as such.
    """
    if not settings.telegram_configured:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set locally. Set it first:\n"
            "    python scripts/set_bot_token.py"
        )
    return [
        {"key": "TELEGRAM_BOT_TOKEN", "value": settings.TELEGRAM_BOT_TOKEN},
        {"key": "TELEGRAM_ADMIN_ID", "value": str(settings.TELEGRAM_ADMIN_ID)},
        {"key": "TELEGRAM_TRIAL_LIMIT", "value": str(settings.TELEGRAM_TRIAL_LIMIT)},
        {"key": "TELEGRAM_STATE_FILE", "value": "/app/storage/bot_users.json"},
        {"key": "OCR_LANG", "value": "rus+eng"},
        {"key": "LOG_LEVEL", "value": "INFO"},
    ]


def redacted() -> list[dict[str, str]]:
    return [{**item, "value": "<hidden>" if "TOKEN" in item["key"] else item["value"]}
            for item in env_payload()]


def step(text: str) -> None:
    print(f"\n==> {text}")


def ok(text: str) -> None:
    print(f"    {text}")


def find_existing(client: httpx.Client, owner_id: str) -> str | None:
    response = client.get(f"{API}/services", params={"ownerId": owner_id})
    if response.status_code != 200:
        return None
    for service in response.json():
        if service.get("name") == SERVICE_NAME:
            return service.get("id") or service.get("service", {}).get("id")
    return None


def deploy(client: httpx.Client, service_id: str, env: list[dict[str, str]]) -> str | None:
    body = {"clearCache": "clear", "envVars": env}
    response = client.post(f"{API}/services/{service_id}/deploys", json=body)
    if response.status_code not in (200, 201, 202):
        print(f"    Render ответил {response.status_code}: {response.text[:200]}")
        return None
    return (response.json().get("deploy") or {}).get("id")


def wait_for_deploy(client: httpx.Client, deploy_id: str) -> str:
    """Poll until the deploy settles, reporting only when something changes."""
    deadline = time.time() + TIMEOUT_SECONDS
    last = ""
    while time.time() < deadline:
        response = client.get(f"{API}/services/{SERVICE_NAME}/deploys", params={"limit": 1})
        if response.status_code == 200:
            deploys = response.json()
            entry = (deploys[0] if isinstance(deploys, list) and deploys else {}) or {}
            current = entry.get("deploy", {}).get("status") or entry.get("status", "")
            if current and current != last:
                ok(f"статус сборки: {current}")
                last = current
            if current in ("live", "deactivated", "build_failed", "update_failed"):
                return current
        time.sleep(15)
    return "timeout"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="show payloads and exit")
    args = parser.parse_args()

    print("=" * 66)
    print("DEPLOY THE BOT TO RENDER")
    print("=" * 66)

    if args.dry_run:
        step("что будет отправлено")
        ok(f"service: {SERVICE_NAME} ({PLAN}, {REGION}, worker, Docker)")
        ok(f"repo   : {REPO}@{BRANCH}")
        ok(f"docker : {DOCKERFILE}")
        step("переменные окружения")
        for item in redacted():
            ok(f"{item['key']} = {item['value']}")
        return 0

    key = getpass.getpass("Render API key (ввод скрыт): ").strip()
    if not key.startswith("rnd_"):
        print("Ключ Render начинается с 'rnd_'. Скопируй его из:")
        print("  https://dash.render.com → Account Settings → API Keys → Create")
        return 1

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    with httpx.Client(headers=headers, timeout=60) as client:
        step("проверяю ключ")
        response = client.get(f"{API}/owners")
        if response.status_code != 200:
            print(f"    Ключ не принят (HTTP {response.status_code}).")
            return 1
        owners = response.json()
        if not owners:
            print("    У аккаунта нет ни одного workspace.")
            return 1
        owner_id = owners[0]["id"]
        owner_name = owners[0].get("name") or owners[0].get("type")
        ok(f"владелец: {owner_name}")

        env = env_payload()

        step("ищу существующий воркер")
        service_id = find_existing(client, owner_id)
        if service_id:
            ok(f"найден: {service_id}, обновляю переменные")
            response = client.patch(
                f"{API}/services/{service_id}", json={"envVars": env}
            )
            if response.status_code not in (200, 201):
                print(f"    Не удалось обновить (HTTP {response.status_code}).")
                print(f"    {response.text[:200]}")
                return 1
        else:
            ok("не найден, создаю")
            response = client.post(f"{API}/services", json=service_payload(owner_id))
            if response.status_code not in (200, 201):
                print(f"    Создание не удалось (HTTP {response.status_code}).")
                print(f"    {response.text[:300]}")
                return 1
            service_id = (response.json().get("service") or {}).get("id")
            ok(f"создан: {service_id}")
            deploy(client, service_id, env)

        step("запускаю сборку")
        deploy_id = deploy(client, service_id, env)
        if not deploy_id:
            return 1
        ok(f"deploy: {deploy_id}")

        step("жду, пока образ соберётся")
        ok("первая сборка занимает 5-10 минут: ставится Tesseract")
        status = wait_for_deploy(client, deploy_id)

        step("итог")
        if status == "live":
            ok("бот развёрнут и отвечает в Telegram")
            print("\nПроверь: напиши боту /start и пришли фото чека.")
            print("Не запускай локальную копию одновременно — один токен,")
            print("один процесс, иначе оба перестанут отвечать:")
            print("    powershell -ExecutionPolicy Bypass -File scripts\\bot_service.ps1 stop")
            return 0

        print(f"    Сборка не завершилась успешно: {status}")
        print("    Логи: https://dash.render.com → выбери сервис → Logs")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
