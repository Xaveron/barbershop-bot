from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.models import Appointment, AppointmentStatus, User
from app.database.repositories.base import BaseRepository


class UserRepository(BaseRepository):
    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(User).where(User.telegram_id == telegram_id)
        return await self.session.scalar(stmt)

    async def get_or_create(
        self,
        *,
        telegram_id: int,
        full_name: str,
        username: str | None = None,
        language_code: str | None = None,
    ) -> User:
        """Идемпотентный upsert пользователя (устойчив к гонке параллельных апдейтов).

        `language_code` записывается только при создании: выбор клиента в меню
        «🌐 Язык» не должен затираться настройкой его приложения Telegram.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(
                telegram_id=telegram_id,
                full_name=full_name,
                username=username,
                language_code=language_code,
            )
            self.session.add(user)
            try:
                await self.session.flush()
            except IntegrityError:
                await self.session.rollback()
                existing = await self.get_by_telegram_id(telegram_id)
                if existing is None:  # pragma: no cover - защитная ветка
                    raise
                user = existing
            return user

        changed = False
        if user.full_name != full_name:
            user.full_name = full_name
            changed = True
        if user.username != username:
            user.username = username
            changed = True
        if user.is_blocked:
            user.is_blocked = False
            changed = True
        if changed:
            await self.session.flush()
        return user

    async def set_language(self, user: User, language: str) -> None:
        user.language_code = language
        await self.session.flush()

    async def set_phone(self, user: User, phone: str) -> None:
        user.phone = phone
        await self.session.flush()

    async def set_blocked(self, user_id: uuid.UUID, *, blocked: bool) -> None:
        user = await self.get(user_id)
        if user is not None:
            user.is_blocked = blocked
            await self.session.flush()

    async def count(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(User)) or 0

    async def list_with_appointment_counts(
        self, *, limit: int = 10, offset: int = 0
    ) -> list[tuple[User, int]]:
        appointments_count = func.count(Appointment.id).label("appointments_count")
        stmt = (
            select(User, appointments_count)
            .outerjoin(
                Appointment,
                (Appointment.user_id == User.id)
                & (Appointment.status != AppointmentStatus.CANCELLED),
            )
            .group_by(User.id)
            .order_by(appointments_count.desc(), User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in rows.all()]
