"""Онбординг арендатора: создание, готовность, активация.

Ни один метод не полагается на глобальный процессный tenant_id — каждый
принимает его явным параметром (см. docs/TENANT_ONBOARDING_DESIGN.md §15),
так что сервис одинаково пригоден и сегодняшнему "один процесс — один
арендатор", и будущей multi-bot фазе.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AuditLogEntry,
    Barber,
    BarberBranch,
    Branch,
    Role,
    StaffMember,
    Tenant,
    TenantStatus,
    WorkingSchedule,
)
from app.database.repositories import (
    BranchRepository,
    ServiceRepository,
    StaffRepository,
    TenantRepository,
)
from app.services.staff import StaffService


@dataclass(slots=True)
class OnboardingReadiness:
    """Структурированный результат проверки готовности — не просто bool
    (см. docs/TENANT_ONBOARDING_DESIGN.md §9): `missing` хранит ключи i18n,
    а не готовый текст, чтобы хендлер сам перевёл их на язык владельца."""

    is_ready: bool
    missing: list[str] = field(default_factory=list)


class TenantOnboardingService:
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.branches = BranchRepository(session, tenant_id)
        self.services = ServiceRepository(session, tenant_id)
        self.staff = StaffRepository(session, tenant_id)

    # --- Готовность -----------------------------------------------------
    async def validate_ready(self) -> OnboardingReadiness:
        """Пересчитывается каждый раз из реальных данных, а не из
        сохранённого "текущего шага" — см. design decision C:
        восстановление после падения/перезапуска не может рассинхронизироваться
        с БД, если шага, который надо синхронизировать, попросту не существует."""
        missing: list[str] = []

        branches = await self.branches.list_active()
        if not branches:
            missing.append("onboarding.missing_branch")

        active_services = await self.services.list_active()
        if not active_services:
            missing.append("onboarding.missing_service")

        has_bookable_barber = await self._has_bookable_barber()
        if not has_bookable_barber:
            missing.append("onboarding.missing_barber")
        elif not await self._has_active_schedule():
            missing.append("onboarding.missing_schedule")

        return OnboardingReadiness(is_ready=not missing, missing=missing)

    async def _has_bookable_barber(self) -> bool:
        """Активный барбер, привязанный хотя бы к одному активному филиалу."""
        stmt = (
            select(func.count())
            .select_from(BarberBranch)
            .join(Barber, Barber.id == BarberBranch.barber_id)
            .join(Branch, Branch.id == BarberBranch.branch_id)
            .where(
                BarberBranch.tenant_id == self.tenant_id,
                Barber.is_active.is_(True),
                Branch.is_active.is_(True),
            )
        )
        return bool(await self.session.scalar(stmt))

    async def _has_active_schedule(self) -> bool:
        """Хотя бы одна строка WorkingSchedule для активного барбера в
        активном филиале. set_day уже гарантирует barber_and_branch_valid
        при создании строки, так что отдельно перепроверять barber_branches
        здесь не нужно."""
        stmt = (
            select(func.count())
            .select_from(WorkingSchedule)
            .join(Barber, Barber.id == WorkingSchedule.barber_id)
            .join(Branch, Branch.id == WorkingSchedule.branch_id)
            .where(
                WorkingSchedule.tenant_id == self.tenant_id,
                Barber.is_active.is_(True),
                Branch.is_active.is_(True),
            )
        )
        return bool(await self.session.scalar(stmt))

    # --- Владелец ---------------------------------------------------------
    async def ensure_owner(
        self, *, telegram_id: int, actor_telegram_id: int
    ) -> StaffMember:
        """Создаёт TENANT_OWNER, либо (если кто-то уже успел — гонка двух
        одновременных /start) возвращает уже существующего. Опирается на
        частичный уникальный индекс uq_staff_members_tenant_id_owner
        (миграция 0009) как на источник истины, а не только на
        предварительную python-проверку "владельца ещё нет" (см.
        docs/TENANT_ONBOARDING_DESIGN.md §11, §18)."""
        existing = await self.staff.get_owner()
        if existing is not None:
            return existing
        try:
            staff = await StaffService(self.session, self.tenant_id).create_staff(
                actor_telegram_id=actor_telegram_id,
                telegram_id=telegram_id,
                role=Role.TENANT_OWNER,
            )
        except IntegrityError:
            await self.session.rollback()
            staff = None
        if staff is not None:
            return staff
        # Либо гонка (кто-то стал владельцем между проверкой и INSERT-ом),
        # либо telegram_id уже есть в staff_members с другой ролью —
        # в обоих случаях переспрашиваем БД, а не изобретаем результат.
        owner = await self.staff.get_owner()
        if owner is not None:
            return owner
        raise RuntimeError("Не удалось создать или найти владельца арендатора.")

    # --- Активация ----------------------------------------------------------
    async def activate(self, *, actor_telegram_id: int) -> OnboardingReadiness:
        """Активация идемпотентна (повторный вызов на уже ACTIVE арендаторе —
        no-op) и всегда перепроверяет готовность на сервере: одного нажатия
        "Готово" клиентом недостаточно (см. docs/TENANT_ONBOARDING_DESIGN.md §13)."""
        tenant = await TenantRepository(self.session).get(self.tenant_id)
        if tenant is None:
            raise RuntimeError("Арендатор не найден.")
        if tenant.status == TenantStatus.ACTIVE:
            return OnboardingReadiness(is_ready=True)

        readiness = await self.validate_ready()
        if not readiness.is_ready:
            return readiness

        tenant.status = TenantStatus.ACTIVE
        self.session.add(
            AuditLogEntry(
                tenant_id=self.tenant_id,
                actor_telegram_id=actor_telegram_id,
                action="tenant.activated",
            )
        )
        await self.session.commit()
        return readiness

    # --- Создание нового арендатора -----------------------------------------
    @staticmethod
    async def create_tenant(
        session: AsyncSession,
        *,
        name: str,
        slug: str,
        timezone: str = "Europe/Chisinau",
        currency: str = "MDL",
    ) -> Tenant:
        """Единственное место, где реально создаётся Tenant с
        status=ONBOARDING (Python-дефолт модели). Статический метод, а не
        обычный: создание нового арендатора по определению происходит ДО
        того, как у нас есть его tenant_id для конструктора сервиса. Не
        привязан ни к одному живому Telegram-хендлеру — в архитектуре "один
        процесс = один tenant_id" (см. app/main.py) нет достижимого UI
        "создать ещё один арендатор в этом же боте"; это протестированный
        сервисный примитив для оператора/будущей платформенной обвязки, а не
        SQL-вставка руками (см. docs/TENANT_ONBOARDING_DESIGN.md §15)."""
        tenant = Tenant(name=name, slug=slug, timezone=timezone, currency=currency)
        session.add(tenant)
        await session.commit()
        return tenant
