"""Платформенная админка: список ботов арендатора, вкл/выкл (Phase 8).

Привязка НОВОГО бота намеренно не живёт здесь — принять сырой bot token
текстовым сообщением в чат было бы понижением безопасности по сравнению с
`python -m app.register_bot` (переменная окружения, никогда не попадающая в
историю переписки Telegram). См. docs/PLATFORM_CONTROL_PLANE.md §Live UI."""

from __future__ import annotations

import uuid

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.callbacks import PlatformCB
from app.bot.keyboards.platform import platform_bots_kb
from app.bot.middlewares.permissions import RequirePlatformOperator
from app.bot.utils import alert, edit_message, parse_uuid
from app.database.models import TelegramBotIdentity
from app.database.repositories import TelegramBotIdentityRepository
from app.services.tenant_management import TenantManagementService

router = Router(name="platform-bots")
router.callback_query.filter(RequirePlatformOperator())


def _bots_text(bots: list[TelegramBotIdentity]) -> str:
    if not bots:
        return (
            "🤖 <b>Боты арендатора</b>\n\nНи один бот ещё не привязан.\n"
            "Запустите: python -m app.register_bot --tenant-id <uuid>"
        )
    lines = [f"{'✅' if b.is_active else '🚫'} {b.username or b.telegram_bot_id}" for b in bots]
    return "🤖 <b>Боты арендатора</b>\n\n" + "\n".join(lines)


async def _render_bots(
    callback: CallbackQuery, session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    bots = await TelegramBotIdentityRepository(session).list_for_tenant(tenant_id)
    await edit_message(callback, _bots_text(bots), platform_bots_kb(str(tenant_id), bots))


@router.callback_query(PlatformCB.filter(F.action == "bots"))
async def show_bots(
    callback: CallbackQuery, callback_data: PlatformCB, session: AsyncSession
) -> None:
    tenant_id = parse_uuid(callback_data.arg)
    if tenant_id is None:
        await alert(callback, "Некорректный арендатор.")
        return
    await _render_bots(callback, session, tenant_id)
    await callback.answer()


@router.callback_query(PlatformCB.filter(F.action == "bot_toggle"))
async def toggle_bot(
    callback: CallbackQuery, callback_data: PlatformCB, session: AsyncSession
) -> None:
    # arg — telegram_bot_id, а не UUID: серверная сторона резолвит саму
    # identity, а не доверяет присланному статусу (см. §Callback security).
    if not callback_data.arg.lstrip("-").isdigit() or callback.from_user is None:
        await alert(callback, "Некорректный bot.")
        return
    telegram_bot_id = int(callback_data.arg)
    repository = TelegramBotIdentityRepository(session)
    current = await repository.get_by_bot_id(telegram_bot_id)
    if current is None:
        await alert(callback, "Bot не найден.")
        return

    service = TenantManagementService(session)
    if current.is_active:
        identity = await service.deactivate_bot(
            telegram_bot_id, actor_telegram_id=callback.from_user.id
        )
    else:
        identity = await service.activate_bot(
            telegram_bot_id, actor_telegram_id=callback.from_user.id
        )
    if identity is None:
        await alert(callback, "Bot не найден.")
        return

    await _render_bots(callback, session, identity.tenant_id)
    await callback.answer("Обновлено")
