"""Отправка напоминаний и служебных уведомлений в Telegram."""

from __future__ import annotations

import asyncio
import logging
import uuid

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.i18n import t
from app.config import Settings
from app.database.models import (
    Appointment,
    AppointmentStatus,
    Feature,
    Notification,
    NotificationKind,
)
from app.database.repositories import NotificationRepository, StaffRepository, UserRepository
from app.services.billing import EntitlementService
from app.services.formatting import appointment_card
from app.services.locale import get_tenant_default_language, resolve_customer_locale
from app.utils.dt import now_utc
from app.utils.text import esc

logger = logging.getLogger(__name__)

REMINDER_KEYS: dict[NotificationKind, str] = {
    NotificationKind.REMINDER_24H: "notify.reminder_24h",
    NotificationKind.REMINDER_2H: "notify.reminder_2h",
}


def client_language(appointment: Appointment, tenant_default_language: str) -> str:
    """Язык клиента: напоминания и уведомления приходят на нём. Резолвится
    через User.language_code -> tenant_default_language -> FALLBACK (Phase
    9E §13) — settings.default_language (процесс-wide) здесь больше не
    участвует, см. app/services/locale.py."""
    return resolve_customer_locale(appointment.user, tenant_default_language)


class NotificationService:
    """Отправляет запланированные напоминания и уведомляет администраторов."""

    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        tenant_id: uuid.UUID,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.settings = settings
        self.tenant_id = tenant_id

    # --- Фоновая рассылка ---------------------------------------------------
    async def dispatch_due(self, *, batch_size: int = 30) -> tuple[int, int]:
        """Отправляет напоминания, время которых наступило.

        Возвращает (sent, errors): отправлено и сколько упало с неожиданной ошибкой.
        """
        sent = 0
        errors = 0
        async with self.session_factory() as session:
            # Тихо ничего не отправляем на тарифе без REMINDERS — это не
            # ошибка клиента и не BillingError: очередь фоновая, поднимать
            # её тут некому (см. docs/BILLING_DESIGN.md §Enforcement).
            # notify_new_appointment/notify_cancelled — операционные
            # уведомления владельцу, а не «напоминание», и этим лимитом
            # не гейтятся.
            if not await EntitlementService(session, self.tenant_id).has_feature(
                Feature.REMINDERS
            ):
                return sent, errors
            repository = NotificationRepository(session)
            users = UserRepository(session, self.tenant_id)
            # Один запрос на весь батч (не на каждое напоминание) — тот же
            # tenant_id обслуживает весь dispatch_due (Phase 9E §14): язык
            # клиента резолвится через appointment.user, а этот дефолт нужен
            # ему только как fallback, если у клиента ничего не сохранено.
            tenant_default_language = await get_tenant_default_language(
                session, self.tenant_id
            )
            try:
                due = await repository.list_due(
                    now=now_utc(), tenant_id=self.tenant_id, limit=batch_size
                )
                for notification in due:
                    appointment = notification.appointment
                    try:
                        async with session.begin_nested():
                            delivered = await self._deliver(
                                notification, appointment, repository, users,
                                tenant_default_language,
                            )
                        if delivered:
                            sent += 1
                    except Exception:
                        logger.exception(
                            "Неожиданная ошибка при доставке напоминания %s", notification.id
                        )
                        errors += 1
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Не удалось обработать очередь напоминаний")
                raise
        if sent:
            logger.info("Отправлено напоминаний: %s", sent)
        return sent, errors

    async def _deliver(
        self,
        notification: Notification,
        appointment: Appointment,
        repository: NotificationRepository,
        users: UserRepository,
        tenant_default_language: str,
    ) -> bool:
        if notification.kind == NotificationKind.RETURN_REMINDER:
            return await self._deliver_return(
                notification, appointment, repository, users, tenant_default_language
            )

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

        lang = client_language(appointment, tenant_default_language)
        text = (
            f"{t(REMINDER_KEYS[notification.kind], lang)}\n\n"
            f"{appointment_card(appointment, appointment.branch.tz)}\n\n"
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

    async def _deliver_return(
        self,
        notification: Notification,
        appointment: Appointment,
        repository: NotificationRepository,
        users: UserRepository,
        tenant_default_language: str,
    ) -> bool:
        if appointment.user.is_blocked:
            await repository.mark_failed(notification, error="user blocked the bot")
            return False

        lang = client_language(appointment, tenant_default_language)
        weeks = self.settings.return_reminder_weeks
        text = t("notify.return_reminder", lang, weeks=weeks, shop=esc(self.settings.shop_name))
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
            logger.warning("Ошибка отправки напоминания «вернись»: %s", exc)
            await repository.mark_failed(notification, error=str(exc))
            return False
        await repository.mark_sent(notification, now=now_utc())
        return True

    # --- Уведомления администраторам ---------------------------------------
    async def notify_admins(self, text: str) -> None:
        """Уведомляет активных TENANT_OWNER/TENANT_ADMIN ЭТОГО арендатора —
        не settings.admin_ids (Phase 9A §C-2: ADMIN_ID/global admin list
        никогда не участвует в бизнес-уведомлениях конкретного арендатора,
        см. docs/PLATFORM_CONTROL_PLANE.md про self-terminating bootstrap
        ADMIN_ID). Пустой список получателей — безопасный no-op."""
        async with self.session_factory() as session:
            recipients = await StaffRepository(
                session, self.tenant_id
            ).list_notification_recipients()
        if not recipients:
            logger.debug(
                "Нет активных владельцев/админов для уведомления арендатора %s", self.tenant_id
            )
            return
        for staff in recipients:
            try:
                await self.bot.send_message(staff.telegram_id, text)
            except TelegramRetryAfter as exc:  # pragma: no cover - зависит от Telegram
                await asyncio.sleep(min(exc.retry_after, 30))
            except (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError) as exc:
                logger.warning(
                    "Не удалось уведомить сотрудника %s: %s", staff.telegram_id, exc
                )

    async def notify_new_appointment(self, appointment: Appointment) -> None:
        # Администратору/владельцу пишем на языке арендатора (Tenant.
        # default_language), а не process-wide settings.default_language
        # (Phase 9E §12) — рассылка на N получателей одним текстом, поэтому
        # это дефолт арендатора, а не персональный язык конкретного
        # сотрудника (см. app/services/locale.py).
        async with self.session_factory() as session:
            lang = await get_tenant_default_language(session, self.tenant_id)
        text = (
            f"{t('notify.new_appointment', lang)}\n\n"
            f"{appointment_card(appointment, appointment.branch.tz, lang=lang)}\n\n"
            f"👤 {esc(appointment.user.display_name)}"
        )
        if appointment.user.phone:
            text += f"\n📞 {esc(appointment.user.phone)}"
        await self.notify_admins(text)

    async def notify_cancelled(self, appointment: Appointment, *, by_client: bool) -> None:
        async with self.session_factory() as session:
            lang = await get_tenant_default_language(session, self.tenant_id)
        key = "notify.cancelled_by_client" if by_client else "notify.cancelled_by_admin"
        text = (
            f"{t(key, lang)}\n\n"
            f"{appointment_card(appointment, appointment.branch.tz, lang=lang)}\n\n"
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
