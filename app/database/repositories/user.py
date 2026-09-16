from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.models import Appointment, AppointmentStatus, User
from app.database.repositories.base import TenantScopedRepository


class UserRepository(TenantScopedRepository):
    async def get(self, user_id: uuid.UUID) -> User | None:
        # session.get() не умеет добавлять tenant_id в WHERE — обязателен select().
        stmt = select(User).where(User.id == user_id, User.tenant_id == self.tenant_id)
        return await self.session.scalar(stmt)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        # tenant_id здесь не для подстраховки: telegram_id уникален только
        # в пределах арендатора, а не глобально.
        stmt = select(User).where(
            User.telegram_id == telegram_id, User.tenant_id == self.tenant_id
        )
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
                tenant_id=self.tenant_id,
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

    async def count(self, *, branch_ids: Collection[uuid.UUID] | None = None) -> int:
        """branch_ids=None — все клиенты арендатора (OWNER/ADMIN). Иначе —
        только клиенты, у которых есть хотя бы одна запись в доступном
        сотруднику филиале: у User нет branch_id (см. §C-1, Phase 9A) —
        видимость определяется через Appointment, а не через новую колонку."""
        if branch_ids is None:
            stmt = select(func.count()).select_from(User).where(User.tenant_id == self.tenant_id)
            return await self.session.scalar(stmt) or 0
        stmt = (
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(Appointment, Appointment.user_id == User.id)
            .where(
                User.tenant_id == self.tenant_id,
                Appointment.tenant_id == self.tenant_id,
                Appointment.branch_id.in_(branch_ids),
            )
        )
        return await self.session.scalar(stmt) or 0

    async def list_with_appointment_counts(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> list[tuple[User, int]]:
        """branch_ids=None — тот же контракт, что count(): без ограничений —
        outer join (клиенты без записей тоже видны); с ограничением — inner
        join на доступные филиалы (клиент виден только если у него есть
        запись там, счётчик — тоже только по этим записям)."""
        appointments_count = func.count(Appointment.id).label("appointments_count")
        join_condition = (
            (Appointment.user_id == User.id)
            & (Appointment.tenant_id == self.tenant_id)
            & (Appointment.status != AppointmentStatus.CANCELLED)
        )
        if branch_ids is None:
            stmt = select(User, appointments_count).outerjoin(Appointment, join_condition)
        else:
            join_condition = join_condition & (Appointment.branch_id.in_(branch_ids))
            stmt = select(User, appointments_count).join(Appointment, join_condition)
        stmt = (
            stmt.where(User.tenant_id == self.tenant_id)
            .group_by(User.id)
            .order_by(appointments_count.desc(), User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in rows.all()]
