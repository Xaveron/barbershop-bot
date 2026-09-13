"""Отправка напоминаний и служебных уведомлений в Telegram."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.i18n import normalize_language, t
from app.config import Settings
from app.database.models import Appointment, AppointmentStatus, Notification, NotificationKind
from app.database.repositories import NotificationRepository, UserRepository
from app.services.formatting import appointment_card
from app.utils.dt import now_utc
from app.utils.text import esc

logger = logging.getLogger(__name__)

REMINDER_KEYS: dict[NotificationKind, str] = {
    NotificationKind.REMINDER_24H: "notify.reminder_24h",
    NotificationKind.REMINDER_2H: "notify.reminder_2h",
}


def client_language(appointment: Appointment, settings: Settings) -> str:
    """Язык клиента: напоминания и уведомления приходят на нём."""
    return normalize_language(appointment.user.language_code, settings.default_language)


class NotificationService:
    """Отправляет запланированные напоминания и уведомляет администраторов."""

    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings
        self.tz = settings.tz

    # --- Фоновая рассылка ---------------------------------------------------
    async def dispatch_due(self, *, batch_size: int = 30) -> int:
        """Отправляет напоминания, время которых наступило. Возвращает число отправленных."""
        sent = 0
        async with self.session_factory() as session:
            repository = NotificationRepository(session)
            users = UserRepository(session)
            try:
                due = await repository.list_due(now=now_utc(), limit=batch_size)
                for notification in due:
                    appointment = notification.appointment
                    delivered = await self._deliver(notification, appointment, repository, users)
                    if delivered:
                        sent += 1
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Не удалось обработать очередь напоминаний")
                raise
        if sent:
            logger.info("Отправлено напоминаний: %s", sent)
        return sent

    async def _deliver(
        self,
        notification: Notification,
        appointment: Appointment,
        repository: NotificationRepository,
        users: UserRepository,
    ) -> bool:
        # Защитные проверки: очередь могла пережить отмену записи или блокировку бота.
        if appointment.status is not AppointmentStatus.CONFIRMED:
            logger.info(
                "Пропускаем напоминание %s: запись %s в статусе %s",
                notification.kind.value,
                appointment.id,
                appointment.status.value,
            )
            await repository.drop_pending(appointment.id)
            return False
        if appointment.user.is_blocked:
            await repository.mark_failed(notification, error="user blocked the bot")
            return False

        lang = client_language(appointment, self.settings)
        text = (
            f"{t(REMINDER_KEYS[notification.kind], lang)}\n\n"
            f"{appointment_card(appointment, self.tz)}\n\n"
            f"📍 {esc(self.settings.shop_address)}"
        )
        try:
            await self.bot.send_message(appointment.user.telegram_id, text)
        except TelegramRetryAfter as exc:
            logger.warning("Flood control: ждём %s c", exc.retry_after)
            await asyncio.sleep(min(exc.retry_after, 30))
            await repository.mark_failed(notification, error=f"retry_after={exc.retry_after}")
            return False
        except TelegramForbiddenError:
            logger.info("Пользователь %s заблокировал бота", appointment.user.telegram_id)
            await users.set_blocked(appointment.user_id, blocked=True)
            await repository.mark_failed(notification, error="bot blocked by user")
            return False
        except (TelegramBadRequest, TelegramNetworkError) as exc:
            logger.warning("Ошибка отправки напоминания: %s", exc)
            await repository.mark_failed(notification, error=str(exc))
            return False
        await repository.mark_sent(notification, now=now_utc())
        return True

    # --- Уведомления администраторам ---------------------------------------
    async def notify_admins(self, text: str) -> None:
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text)
            except TelegramRetryAfter as exc:  # pragma: no cover - зависит от Telegram
                await asyncio.sleep(min(exc.retry_after, 30))
            except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError) as exc:
                logger.warning("Не удалось уведомить администратора %s: %s", admin_id, exc)

    async def notify_new_appointment(self, appointment: Appointment) -> None:
        # Администратору пишем на языке барбершопа (DEFAULT_LANGUAGE).
        lang = self.settings.default_language
        text = (
            f"{t('notify.new_appointment', lang)}\n\n"
            f"{appointment_card(appointment, self.tz, lang=lang)}\n\n"
            f"👤 {esc(appointment.user.display_name)}"
        )
        if appointment.user.phone:
            text += f"\n📞 {esc(appointment.user.phone)}"
        await self.notify_admins(text)

    async def notify_cancelled(self, appointment: Appointment, *, by_client: bool) -> None:
        lang = self.settings.default_language
        key = "notify.cancelled_by_client" if by_client else "notify.cancelled_by_admin"
        text = (
            f"{t(key, lang)}\n\n"
            f"{appointment_card(appointment, self.tz, lang=lang)}\n\n"
            f"👤 {esc(appointment.user.display_name)}"
        )
        await self.notify_admins(text)

    async def notify_client(self, telegram_id: int, text: str) -> bool:
        """Сообщение клиенту от лица барбершопа (перенос/отмена админом)."""
        try:
            await self.bot.send_message(telegram_id, text)
        except TelegramRetryAfter as exc:  # pragma: no cover
            await asyncio.sleep(min(exc.retry_after, 30))
            return False
        except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError) as exc:
            logger.warning("Не удалось уведомить клиента %s: %s", telegram_id, exc)
            return False
        return True
