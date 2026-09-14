"""Фоновые задачи."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.models import NotificationKind
from app.database.repositories import AppointmentRepository, NotificationRepository
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
        _sent, errors = await service.dispatch_due()
        if errors:
            logger.warning("Напоминаний с ошибкой: %s", errors)
            await service.notify_admins(
                f"⚠️ <b>Ошибка доставки напоминаний</b>\n\n"
                f"Не удалось доставить: {errors} шт.\n"
                f"Проверьте логи бота."
            )
    except Exception:
        logger.exception("Ошибка при рассылке напоминаний")


async def schedule_return_reminders(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Планирует напоминание «пора к барберу» через N недель после последнего визита."""
    weeks = settings.return_reminder_weeks
    if weeks == 0:
        return

    now = now_utc()
    target = now - timedelta(weeks=weeks)
    window_start = target - timedelta(hours=12)
    window_end = target + timedelta(hours=12)

    async with session_factory() as session:
        try:
            appt_repo = AppointmentRepository(session)
            notif_repo = NotificationRepository(session)

            appointments = await appt_repo.list_completed_in_ends_window(
                window_start=window_start, window_end=window_end
            )

            scheduled = 0
            seen_users: set[uuid.UUID] = set()
            for appt in appointments:
                if appt.user_id in seen_users or appt.user.is_blocked:
                    continue
                seen_users.add(appt.user_id)

                upcoming = await appt_repo.count_active_for_user(user_id=appt.user_id, now=now)
                if upcoming > 0:
                    continue

                created = await notif_repo.schedule(
                    appointment_id=appt.id,
                    kind=NotificationKind.RETURN_REMINDER,
                    scheduled_for=now,
                )
                if created:
                    scheduled += 1

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Ошибка при планировании напоминаний «вернись»")
            return

    if scheduled:
        logger.info("Запланировано напоминаний «пора к барберу»: %s", scheduled)


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
