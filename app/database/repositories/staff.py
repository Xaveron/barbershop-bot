from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.database.models import Barber, Role, StaffMember
from app.database.repositories.base import TenantScopedRepository


class StaffRepository(TenantScopedRepository):
    async def get(self, staff_id: uuid.UUID) -> StaffMember | None:
        # session.get() не умеет добавлять tenant_id в WHERE — обязателен select().
        stmt = select(StaffMember).where(
            StaffMember.id == staff_id, StaffMember.tenant_id == self.tenant_id
        )
        return await self.session.scalar(stmt)

    async def get_by_telegram_id(self, telegram_id: int) -> StaffMember | None:
        stmt = select(StaffMember).where(
            StaffMember.telegram_id == telegram_id, StaffMember.tenant_id == self.tenant_id
        )
        return await self.session.scalar(stmt)

    async def list_all(
        self, *, limit: int | None = None, offset: int = 0
    ) -> list[StaffMember]:
        """limit=None — полный список (используется операционными флоу,
        которым нужны ВСЕ сотрудники, а не одна страница); limit задан —
        одна страница для admin-списка (см. Phase 9C §M-6). created_at, id —
        стабильный порядок: id как tie-breaker гарантирует отсутствие
        дублей/пропусков между страницами даже при совпадении created_at."""
        stmt = (
            select(StaffMember)
            .where(StaffMember.tenant_id == self.tenant_id)
            .order_by(StaffMember.created_at, StaffMember.id)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))

    async def count_all(self) -> int:
        stmt = select(func.count()).select_from(StaffMember).where(
            StaffMember.tenant_id == self.tenant_id
        )
        return await self.session.scalar(stmt) or 0

    async def set_language(self, staff: StaffMember, language: str) -> None:
        """Личное предпочтение (Phase 9E §11) — не влияет на Tenant.
        default_language и на других сотрудников (см. app/services/locale.py)."""
        staff.language = language
        await self.session.flush()

    async def has_any_staff(self) -> bool:
        """Используется онбордингом: пока у арендатора нет вообще ни одного
        сотрудника, /start от ADMIN_ID вправе стать TENANT_OWNER (см.
        docs/TENANT_ONBOARDING_DESIGN.md) — после первой строки этот путь
        больше никогда не срабатывает."""
        stmt = select(func.count()).select_from(StaffMember).where(
            StaffMember.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))

    async def get_owner(self) -> StaffMember | None:
        stmt = select(StaffMember).where(
            StaffMember.tenant_id == self.tenant_id,
            StaffMember.role == Role.TENANT_OWNER,
            StaffMember.is_active.is_(True),
        )
        return await self.session.scalar(stmt)

    async def list_notification_recipients(self) -> list[StaffMember]:
        """Получатели операционных уведомлений (новая запись, отмена,
        ошибка доставки напоминаний) — только активные TENANT_OWNER/
        TENANT_ADMIN ЭТОГО арендатора (см. app/services/notifications.py::
        notify_admins, Phase 9A §C-2). MANAGER/RECEPTIONIST/BARBER сознательно
        не входят — операционные уведомления адресованы владельцу бизнеса,
        а не рядовому персоналу."""
        stmt = select(StaffMember).where(
            StaffMember.tenant_id == self.tenant_id,
            StaffMember.is_active.is_(True),
            StaffMember.role.in_((Role.TENANT_OWNER, Role.TENANT_ADMIN)),
        )
        return list(await self.session.scalars(stmt))

    async def create(
        self, *, telegram_id: int, role: Role, barber_id: uuid.UUID | None = None
    ) -> StaffMember | None:
        """Возвращает None, если barber_id указан, но принадлежит другому
        арендатору — тот же паттерн, что ScheduleRepository.set_day (см. Phase
        1.5 audit): «нет строки» и «чужой ресурс» не должны быть неразличимы."""
        if barber_id is not None and not await self._barber_belongs_to_tenant(barber_id):
            return None
        staff = StaffMember(
            tenant_id=self.tenant_id, telegram_id=telegram_id, role=role, barber_id=barber_id
        )
        self.session.add(staff)
        await self.session.flush()
        return staff

    async def _barber_belongs_to_tenant(self, barber_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(Barber).where(
            Barber.id == barber_id, Barber.tenant_id == self.tenant_id
        )
        return bool(await self.session.scalar(stmt))
