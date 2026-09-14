from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from app.database.models import (
    Appointment,
    AppointmentStatus,
    Notification,
    NotificationKind,
    NotificationStatus,
)
from app.database.repositories.base import BaseRepository

MAX_ATTEMPTS = 3


class NotificationRepository(BaseRepository):
    async def schedule(
        self,
        *,
        appointment_id: uuid.UUID,
        kind: NotificationKind,
        scheduled_for: datetime,
    ) -> bool:
        """Планирует напоминание. Возвращает True, если строка была создана.

        ON CONFLICT DO NOTHING + UNIQUE(appointment_id, kind) = идемпотентность.
        """
        stmt = (
            pg_insert(Notification)
            .values(
                id=uuid.uuid4(),
                appointment_id=appointment_id,
                kind=kind.value,
                status=NotificationStatus.PENDING.value,
                scheduled_for=scheduled_for,
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=[Notification.appointment_id, Notification.kind])
        )
        result = await self.session.execute(stmt)
        return bool(result.rowcount)

    async def schedule_many(
        self, *, appointment_id: uuid.UUID, items: Sequence[tuple[NotificationKind, datetime]]
    ) -> int:
        """Планирует несколько напоминаний одним INSERT-ом. Возвращает число созданных."""
        if not items:
            return 0
        values = [
            {
                "id": uuid.uuid4(),
                "appointment_id": appointment_id,
                "kind": kind.value,
                "status": NotificationStatus.PENDING.value,
                "scheduled_for": scheduled_for,
                "attempts": 0,
            }
            for kind, scheduled_for in items
        ]
        stmt = pg_insert(Notification).values(values).on_conflict_do_nothing(
            index_elements=[Notification.appointment_id, Notification.kind]
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)

    async def list_due(self, *, now: datetime, limit: int = 50) -> list[Notification]:
        stmt = (
            select(Notification)
            .join(Appointment, Notification.appointment_id == Appointment.id)
            # selectinload (а не joinedload): FOR UPDATE несовместим с LEFT OUTER JOIN
            .options(selectinload(Notification.appointment))
            .where(
                Notification.status == NotificationStatus.PENDING,
                Notification.scheduled_for <= now,
                Notification.attempts < MAX_ATTEMPTS,
                or_(
                    and_(
                        Notification.kind != NotificationKind.RETURN_REMINDER,
                        Appointment.status == AppointmentStatus.CONFIRMED,
                        Appointment.starts_at > now,
                    ),
                    and_(
                        Notification.kind == NotificationKind.RETURN_REMINDER,
                        Appointment.status == AppointmentStatus.COMPLETED,
                    ),
                ),
            )
            .order_by(Notification.scheduled_for)
            .limit(limit)
            .with_for_update(of=Notification, skip_locked=True)
        )
        return list((await self.session.scalars(stmt)).unique())

    async def mark_sent(self, notification: Notification, *, now: datetime) -> None:
        notification.status = NotificationStatus.SENT
        notification.sent_at = now
        notification.attempts += 1
        notification.last_error = None
        await self.session.flush()

    async def mark_failed(self, notification: Notification, *, error: str) -> None:
        notification.attempts += 1
        notification.last_error = error[:500]
        if notification.attempts >= MAX_ATTEMPTS:
            notification.status = NotificationStatus.FAILED
        await self.session.flush()

    async def drop_pending(self, appointment_id: uuid.UUID) -> int:
        """Удаляет неотправленные напоминания (отмена/перенос записи)."""
        stmt = delete(Notification).where(
            Notification.appointment_id == appointment_id,
            Notification.status == NotificationStatus.PENDING,
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0
