"""Мини-заглушка Telegram Bot API — прогон бота без настоящего Telegram.

Запуск:
    python tools/fake_bot_api.py                     # слушает 127.0.0.1:8081
    TELEGRAM_API_BASE=http://127.0.0.1:8081 python -m app.main
    python tools/demo_client.py                      # прогоняет сценарий записи

Только для локальной отладки: авторизации нет, апдейты берутся из очереди.

Поднимает HTTP-сервер, совместимый с форматом `{base}/bot{token}/{method}`,
и позволяет складывать апдейты в очередь (`/_inject`) и читать всё, что бот
отправил наружу (`/_outbox`). Настоящего Telegram не требуется.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time

from aiohttp import web

UPDATES: asyncio.Queue = asyncio.Queue()
OUTBOX: list[dict] = []
MESSAGE_IDS = itertools.count(1000)


def ok(result):
    return web.json_response({"ok": True, "result": result})


async def payload(request: web.Request) -> dict:
    if request.content_type == "application/json":
        return await request.json()
    data = await request.post()
    parsed = {}
    for key, value in data.items():
        try:
            parsed[key] = json.loads(value)
        except (TypeError, ValueError):
            parsed[key] = value
    return parsed


def message_stub(chat_id, text):
    return {
        "message_id": next(MESSAGE_IDS),
        "date": int(time.time()),
        "chat": {"id": int(chat_id), "type": "private"},
        "from": {"id": 1, "is_bot": True, "first_name": "Bot", "username": "local_bot"},
        "text": text or "",
    }


async def api(request: web.Request) -> web.Response:
    method = request.match_info["method"]
    data = await payload(request)

    if method == "getMe":
        return ok(
            {
                "id": 123456789,
                "is_bot": True,
                "first_name": "Barbershop",
                "username": "local_barbershop_bot",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
                "supports_inline_queries": False,
            }
        )

    if method == "getUpdates":
        timeout = float(data.get("timeout", 1) or 1)
        updates = []
        try:
            updates.append(await asyncio.wait_for(UPDATES.get(), timeout=min(timeout, 5)))
        except TimeoutError:
            return ok([])
        while not UPDATES.empty():
            updates.append(UPDATES.get_nowait())
        return ok(updates)

    if method in {"sendMessage", "editMessageText"}:
        OUTBOX.append(
            {
                "method": method,
                "chat_id": data.get("chat_id"),
                "text": data.get("text"),
                "reply_markup": data.get("reply_markup"),
            }
        )
        return ok(message_stub(data.get("chat_id", 0), data.get("text")))

    if method == "sendDocument":
        OUTBOX.append(
            {"method": method, "chat_id": data.get("chat_id"), "text": data.get("caption")}
        )
        return ok(message_stub(data.get("chat_id", 0), data.get("caption")))

    if method == "answerCallbackQuery":
        OUTBOX.append({"method": method, "text": data.get("text")})
        return ok(True)

    return ok(True)


async def inject(request: web.Request) -> web.Response:
    await UPDATES.put(await request.json())
    return web.json_response({"queued": True})


async def outbox(request: web.Request) -> web.Response:
    drained = list(OUTBOX)
    OUTBOX.clear()
    return web.json_response(drained)


def main() -> None:
    app = web.Application()
    app.router.add_route("*", "/bot{token}/{method}", api)
    app.router.add_post("/_inject", inject)
    app.router.add_get("/_outbox", outbox)
    web.run_app(app, host="127.0.0.1", port=8081, print=None)


if __name__ == "__main__":
    main()
