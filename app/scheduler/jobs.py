"""Фоновые задачи."""

from __future__ import annotations

import logging

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.repositories import AppointmentRepository
from app.services.notifications import NotificationService
from app.utils.dt import now_utc

logger = logging.getLogger(__name__)


async def send_due_reminders(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Рассылает напоминания за 24 часа и за 2 часа до визита."""
    service = NotificationService(bot, session_factory, settings)
    try:
        await service.dispatch_due()
    except Exception:
        logger.exception("Ошибка при рассылке напоминаний")


async def complete_past_appointments(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Переводит прошедшие подтверждённые записи в статус «завершена»."""
    async with session_factory() as session:
        try:
            updated = await AppointmentRepository(session).mark_past_as_completed(now=now_utc())
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Ошибка при закрытии прошедших записей")
            return
    if updated:
        logger.info("Записей переведено в статус completed: %s", updated)
