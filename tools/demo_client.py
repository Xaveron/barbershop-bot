"""Демо-сценарий: кладёт апдейты в tools/fake_bot_api.py и печатает ответы бота.

Перед запуском должны работать: PostgreSQL, `python tools/fake_bot_api.py`
и сам бот с TELEGRAM_API_BASE=http://127.0.0.1:8081.
ADMIN_ID для демо-админа — 555000.
"""

from __future__ import annotations

import asyncio
import sys
import time

import aiohttp

BASE = "http://127.0.0.1:8081"
CLIENT = 777100
ADMIN = 555000

state: dict[str, list] = {"buttons": []}


async def inject(session: aiohttp.ClientSession, update: dict) -> None:
    async with session.post(f"{BASE}/_inject", json=update) as response:
        await response.read()


async def outbox(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(f"{BASE}/_outbox") as response:
        return await response.json()


def message(text: str, user_id: int) -> dict:
    return {
        "update_id": int(time.time() * 1000) % 100000,
        "message": {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Пётр", "username": "petru"},
            "text": text,
        },
    }


def callback(data: str, user_id: int) -> dict:
    return {
        "update_id": int(time.time() * 1000) % 100000 + 1,
        "callback_query": {
            "id": str(time.time()),
            "from": {"id": user_id, "is_bot": False, "first_name": "Пётр", "username": "petru"},
            "chat_instance": "1",
            "data": data,
            "message": {
                "message_id": 500,
                "date": int(time.time()),
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                "text": "предыдущее",
            },
        },
    }


async def step(session: aiohttp.ClientSession, label: str, update: dict) -> None:
    await inject(session, update)
    await asyncio.sleep(1.2)
    replies = await outbox(session)
    print(f"\n=== {label} ===")
    for reply in replies:
        text = (reply.get("text") or "").strip()
        if text:
            print(text)
        markup = reply.get("reply_markup")
        if isinstance(markup, dict) and markup.get("inline_keyboard"):
            buttons = [b for row in markup["inline_keyboard"] for b in row]
            state["buttons"] = [(b.get("text"), b.get("callback_data")) for b in buttons]
            print("  [кнопки] " + " | ".join(str(b.get("text")) for b in buttons))


def pick(prefix: str, index: int = 0) -> str:
    matches = [data for _, data in state["buttons"] if data and data.startswith(prefix)]
    if not matches:
        raise SystemExit(f"нет кнопок {prefix}: {state['buttons']}")
    return matches[index]


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        await step(session, "Клиент: /start", message("/start", CLIENT))
        await step(session, "Клиент: 💈 Записаться", callback("m:book", CLIENT))
        await step(session, "Клиент: выбирает услугу", callback(pick("sv:"), CLIENT))
        await step(session, "Клиент: выбирает барбера", callback(pick("br:"), CLIENT))
        await step(session, "Клиент: выбирает дату", callback(pick("dt:", 1), CLIENT))
        await step(session, "Клиент: выбирает время", callback(pick("tm:", 4), CLIENT))
        await step(session, "Клиент: ✅ Подтвердить", callback("cf:yes", CLIENT))
        await step(session, "Клиент: 📅 Мои записи", callback("m:my", CLIENT))
        await step(session, "Клиент: открывает запись", callback(pick("ap:view"), CLIENT))
        await step(session, "Клиент: 💇 Услуги", callback("m:services", CLIENT))
        await step(session, "Клиент: 📍 Контакты", callback("m:contacts", CLIENT))
        await step(session, "Чужой: пробует админку", callback("ad:stats:", 777999))
        await step(session, "Админ: /admin", message("/admin", ADMIN))
        await step(session, "Админ: 📊 Статистика", callback("ad:stats:", ADMIN))
        await step(session, "Админ: 📅 Записи", callback("ad:appts:0", ADMIN))
        await step(session, "Админ: карточка записи", callback(pick("ad:appt:"), ADMIN))
        await step(session, "Админ: 📥 Экспорт CSV за 30 дней", callback("ad:export_do:30", ADMIN))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit as exc:  # pragma: no cover
        print(exc, file=sys.stderr)
        raise
