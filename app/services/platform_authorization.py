"""Платформенная авторизация — отдельно от tenant RBAC (Phase 8).

Никакого tenant_id здесь: платформенный оператор авторизуется сам по себе,
не "в контексте" какого-либо арендатора (см. docs/PLATFORM_CONTROL_PLANE.md).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import AuditLogEntry, PlatformOperator, PlatformRole
from app.database.repositories import PlatformOperatorRepository


class PlatformAuthorizationError(Exception):
    """Аналог AuthorizationError (app/services/authorization.py): несёт ключ
    перевода, а не готовый текст."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class PlatformAuthorizationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.operators = PlatformOperatorRepository(session)

    async def is_operator(self, telegram_id: int | None) -> bool:
        """True для активного PlatformOperator. Если ни одного оператора ещё
        не существует, ADMIN_ID временно действует как bootstrap-сигнал —
        САМОЗАВЕРШАЮЩЕЕСЯ окно: как только появляется хотя бы один реальный
        PlatformOperator (через app/bootstrap_platform_admin.py — никогда
        неявно из живого апдейта), ADMIN_ID перестаёт учитываться навсегда.
        Это и есть «ADMIN_ID больше не постоянный обход авторизации»."""
        if telegram_id is None:
            return False
        row = await self.operators.get_by_telegram_id(telegram_id)
        if row is not None and row.is_active:
            return True
        if not self.settings.is_admin(telegram_id):
            return False
        return not await self.operators.any_exist()

    async def require_operator(self, telegram_id: int | None) -> None:
        if not await self.is_operator(telegram_id):
            raise PlatformAuthorizationError("platform.no_rights")

    # --- Управление платформенными операторами -------------------------------
    # Отдельно от is_operator/require_operator (чтение прав) намеренно —
    # тот же принцип, что AuthorizationService (чтение) vs StaffService
    # (мутация) в tenant RBAC (Phase 2).
    async def create_operator(
        self, *, telegram_user_id: int, actor_telegram_id: int
    ) -> PlatformOperator:
        operator = await self.operators.create(
            telegram_user_id=telegram_user_id, role=PlatformRole.PLATFORM_ADMIN
        )
        self.session.add(
            AuditLogEntry(
                tenant_id=None,
                actor_telegram_id=actor_telegram_id,
                target_telegram_id=telegram_user_id,
                action="platform_operator.created",
            )
        )
        await self.session.commit()
        return operator

    async def deactivate_operator(
        self, telegram_user_id: int, *, actor_telegram_id: int
    ) -> PlatformOperator | None:
        operator = await self.operators.get_by_telegram_id(telegram_user_id)
        if operator is None:
            return None
        operator.is_active = False
        self.session.add(
            AuditLogEntry(
                tenant_id=None,
                actor_telegram_id=actor_telegram_id,
                target_telegram_id=telegram_user_id,
                action="platform_operator.deactivated",
            )
        )
        await self.session.commit()
        return operator
