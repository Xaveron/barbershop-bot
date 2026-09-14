"""Сервис бронирования: создание, отмена и перенос записей.

Защита от двойного бронирования выстроена в три слоя:
1. Клиенту показываются только свободные слоты.
2. Внутри транзакции берётся advisory-lock по барберу и слот перепроверяется.
3. EXCLUDE-констрейнт PostgreSQL физически запрещает пересечение интервалов.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import (
    Appointment,
    AppointmentStatus,
    CancelledBy,
    NotificationKind,
    User,
)
from app.database.repositories import (
    AppointmentRepository,
    BarberRepository,
    BarberServiceRepository,
    BranchRepository,
    NotificationRepository,
    ServiceRepository,
)
from app.services import rules
from app.services.schedule import ScheduleService
from app.utils.dt import now_utc, to_utc

logger = logging.getLogger(__name__)

REMINDER_OFFSETS: tuple[tuple[NotificationKind, int], ...] = (
    (NotificationKind.REMINDER_24H, 24 * 60),
    (NotificationKind.REMINDER_2H, 2 * 60),
)

# Имя EXCLUDE-констрейнта из миграции 0001.
OVERLAP_CONSTRAINT = "excl_appointments_barber_no_overlap"

# Захват advisory-lock: короткие попытки вместо бесконечного ожидания.
# Блокирующий вариант держал бы соединение из пула до statement_timeout (15 с),
# и при наплыве клиентов пул закончился бы раньше, чем очередь.
LOCK_ATTEMPTS = 14
# Экспоненциальная задержка: первые попытки почти без ожидания (обычная
# конкуренция разрешается за десятки миллисекунд), дальше — реже, суммарно ~3 с.
LOCK_RETRY_MIN_DELAY = 0.02
LOCK_RETRY_MAX_DELAY = 0.4


class BookingError(Exception):
    """Ошибка бронирования: несёт ключ перевода, а не готовый текст.

    Сообщение собирается в хендлере на языке конкретного пользователя.
    """

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class SlotUnavailableError(BookingError):
    pass


class AppointmentNotFoundError(BookingError):
    pass


class TooManyActiveAppointmentsError(BookingError):
    pass


def _advisory_lock_key(entity_id: uuid.UUID) -> int:
    """Стабильный bigint-ключ блокировки из UUID (барбера или клиента)."""
    return int.from_bytes(entity_id.bytes[:8], "big", signed=True)


class BookingService:
    def __init__(self, session: AsyncSession, settings: Settings, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.settings = settings
        self.tenant_id = tenant_id
        self.appointments = AppointmentRepository(session, tenant_id)
        self.services = ServiceRepository(session, tenant_id)
        self.barbers = BarberRepository(session, tenant_id)
        self.branches = BranchRepository(session, tenant_id)
        self.barber_services = BarberServiceRepository(session, tenant_id)
        self.notifications = NotificationRepository(session)
        # Не строим ScheduleService здесь: branch_id — параметр конкретного
        # вызова (create_appointment получает выбранный клиентом филиал,
        # reschedule_appointment — филиал уже существующей записи), а не
        # что-то одно на весь BookingService, как tenant_id.

    # --- Создание -----------------------------------------------------------
    async def create_appointment(
        self,
        *,
        user: User,
        branch_id: uuid.UUID,
        barber_id: uuid.UUID,
        service_id: uuid.UUID,
        start: datetime,
        comment: str | None = None,
    ) -> Appointment:
        service = await self.services.get_active(service_id)
        if service is None:
            raise BookingError("error.service_unavailable")
        barber = await self.barbers.get_active(barber_id)
        if barber is None:
            raise BookingError("error.barber_unavailable")
        branch = await self.branches.get_active(branch_id)
        if branch is None:
            raise BookingError("error.branch_unavailable")
        if not await self.branches.barber_works_at_branch(barber_id=barber_id, branch_id=branch_id):
            raise BookingError("error.barber_not_at_branch")
        if not await self.branches.service_available_at_branch(
            service_id=service_id, branch_id=branch_id
        ):
            raise BookingError("error.service_not_at_branch")
        if not await self.barber_services.barber_provides_service(
            barber_id=barber_id, service_id=service_id
        ):
            raise BookingError("error.barber_not_provide_service")

        now = now_utc()
        # Лочим клиента до чтения счётчика: иначе два параллельных запроса на
        # разных барберов/слотах оба проскочат проверку лимита до commit друг друга.
        await self._lock_user(user.id)
        active = await self.appointments.count_active_for_user(user_id=user.id, now=now)
        try:
            rules.ensure_within_limit(active, self.settings.max_active_appointments)
        except rules.RuleViolationError as exc:
            raise TooManyActiveAppointmentsError(exc.key, **exc.params) from exc

        start_utc = to_utc(start)
        await self._lock_barber(barber_id)

        schedule = ScheduleService(self.session, self.settings, self.tenant_id, branch)
        free = await schedule.is_slot_available(
            barber_id=barber_id,
            start=start_utc,
            duration_minutes=service.duration_minutes,
            exclude_appointment_id=None,
        )
        if not free:
            raise SlotUnavailableError("error.slot_busy")

        appointment = Appointment(
            tenant_id=self.tenant_id,
            branch_id=branch_id,
            user_id=user.id,
            barber_id=barber.id,
            service_id=service.id,
            starts_at=start_utc,
            ends_at=start_utc + timedelta(minutes=service.duration_minutes),
            status=AppointmentStatus.CONFIRMED,
            price=service.price,
            currency=service.currency,
            duration_minutes=service.duration_minutes,
            comment=comment,
        )
        # Проставляем связи вручную: объект новый, ленивая загрузка после
        # commit в async-контексте недопустима.
        appointment.user = user
        appointment.barber = barber
        appointment.service = service
        self.session.add(appointment)

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if OVERLAP_CONSTRAINT in str(exc.orig):
                logger.info("Гонка при бронировании: слот %s уже занят", start_utc)
                raise SlotUnavailableError("error.slot_race") from exc
            logger.exception("Ошибка целостности при создании записи")
            raise BookingError("error.create_failed") from exc

        await self._plan_reminders(appointment)
        await self.session.commit()
        logger.info(
            "Создана запись %s: барбер=%s услуга=%s время=%s",
            appointment.id,
            barber.name,
            service.name,
            start_utc.isoformat(),
        )
        return appointment

    # --- Отмена -------------------------------------------------------------
    async def cancel_appointment(
        self,
        *,
        appointment_id: uuid.UUID,
        cancelled_by: CancelledBy,
        actor_user_id: uuid.UUID | None = None,
    ) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        if actor_user_id is not None and appointment.user_id != actor_user_id:
            raise AppointmentNotFoundError("error.appointment_not_found")

        now = now_utc()
        if cancelled_by == CancelledBy.CLIENT:
            self._check(rules.ensure_can_cancel, appointment, now,
                        self.settings.cancel_min_lead_minutes)
        else:
            self._check(rules.ensure_confirmed, appointment)

        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = now
        appointment.cancelled_by = cancelled_by
        await self.notifications.drop_pending(appointment.id)
        await self.session.commit()
        logger.info("Запись %s отменена (%s)", appointment.id, cancelled_by.value)
        return appointment

    async def mark_no_show(self, *, appointment_id: uuid.UUID) -> Appointment:
        """Клиент не пришёл: слот считается использованным, но не оплаченным."""
        appointment = await self._get_or_raise(appointment_id)
        self._check(rules.ensure_confirmed, appointment)
        appointment.status = AppointmentStatus.NO_SHOW
        await self.notifications.drop_pending(appointment.id)
        await self.session.commit()
        logger.info("Запись %s отмечена как «клиент не пришёл»", appointment.id)
        return appointment

    # --- Перенос ------------------------------------------------------------
    async def reschedule_appointment(
        self,
        *,
        appointment_id: uuid.UUID,
        new_start: datetime,
        by_admin: bool = False,
        actor_user_id: uuid.UUID | None = None,
    ) -> Appointment:
        appointment = await self._get_or_raise(appointment_id)
        if actor_user_id is not None and appointment.user_id != actor_user_id:
            raise AppointmentNotFoundError("error.appointment_not_found")

        now = now_utc()
        if by_admin:
            self._check(rules.ensure_confirmed, appointment)
        else:
            self._check(rules.ensure_can_reschedule, appointment, now,
                        self.settings.cancel_min_lead_minutes)

        new_start_utc = to_utc(new_start)
        await self._lock_barber(appointment.barber_id)

        # Перенос не меняет филиал записи — используем её собственный branch
        # (уже подгружен eager'ом), а не выбор нового (переезд между
        # филиалами — отдельная функция, не эта).
        schedule = ScheduleService(
            self.session, self.settings, self.tenant_id, appointment.branch
        )
        free = await schedule.is_slot_available(
            barber_id=appointment.barber_id,
            start=new_start_utc,
            duration_minutes=appointment.duration_minutes,
            exclude_appointment_id=appointment.id,
        )
        if not free:
            raise SlotUnavailableError("error.slot_busy")

        appointment.starts_at = new_start_utc
        appointment.ends_at = new_start_utc + timedelta(minutes=appointment.duration_minutes)
        await self.notifications.drop_pending(appointment.id)

        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if OVERLAP_CONSTRAINT in str(exc.orig):
                raise SlotUnavailableError("error.slot_race") from exc
            raise BookingError("error.move_failed") from exc

        await self._plan_reminders(appointment)
        await self.session.commit()
        logger.info("Запись %s перенесена на %s", appointment.id, new_start_utc.isoformat())
        return appointment

    # --- Вспомогательное ----------------------------------------------------
    async def get_appointment(self, appointment_id: uuid.UUID) -> Appointment | None:
        return await self.appointments.get(appointment_id)

    async def list_upcoming_for_user(self, user: User) -> list[Appointment]:
        return await self.appointments.list_upcoming_for_user(user_id=user.id, now=now_utc())

    async def _get_or_raise(self, appointment_id: uuid.UUID) -> Appointment:
        appointment = await self.appointments.get(appointment_id)
        if appointment is None:
            raise AppointmentNotFoundError("error.appointment_not_found")
        return appointment

    @staticmethod
    def _check(rule, *args) -> None:
        try:
            rule(*args)
        except rules.RuleViolationError as exc:
            raise BookingError(exc.key, **exc.params) from exc

    async def _lock_barber(self, barber_id: uuid.UUID) -> None:
        """Transaction-scoped advisory lock — сериализует записи к одному барберу."""
        await self._acquire_lock(barber_id, what="барбер")

    async def _lock_user(self, user_id: uuid.UUID) -> None:
        """Transaction-scoped advisory lock — сериализует создание записей одним клиентом.

        Без неё две параллельные заявки одного клиента (разные барберы/слоты, поэтому
        _lock_barber их не разводит) обе читают count_active_for_user до commit друг
        друга и обе проходят проверку max_active_appointments — TOCTOU-гонка.
        """
        await self._acquire_lock(user_id, what="клиент")

    async def _acquire_lock(self, entity_id: uuid.UUID, *, what: str) -> None:
        lock_key = _advisory_lock_key(entity_id)
        for attempt in range(1, LOCK_ATTEMPTS + 1):
            acquired = await self.session.scalar(
                text("SELECT pg_try_advisory_xact_lock(CAST(:lock_key AS bigint))"),
                {"lock_key": lock_key},
            )
            if acquired:
                return
            logger.debug("%s %s занят другой транзакцией (попытка %s)", what, entity_id, attempt)
            delay = min(LOCK_RETRY_MIN_DELAY * 2 ** (attempt - 1), LOCK_RETRY_MAX_DELAY)
            await asyncio.sleep(delay)

        logger.warning("Не удалось взять блокировку (%s %s)", what, entity_id)
        raise BookingError("error.barber_locked")

    async def _plan_reminders(self, appointment: Appointment) -> None:
        now = now_utc()
        # Запись могла быть создана позже точки напоминания — такие пропускаем.
        planned = [
            (kind, appointment.starts_at - timedelta(minutes=offset_minutes))
            for kind, offset_minutes in REMINDER_OFFSETS
            if appointment.starts_at - timedelta(minutes=offset_minutes) > now
        ]
        await self.notifications.schedule_many(appointment_id=appointment.id, items=planned)

