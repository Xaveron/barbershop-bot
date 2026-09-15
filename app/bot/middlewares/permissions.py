"""Фильтры доступа к разделам админ-панели: платформенный оператор
(PlatformOperator — Phase 8, data["is_super_admin"] уже резолвлен
StaffContextMiddleware) либо активный StaffMember арендатора с нужным
правом. Отдельно от app/bot/middlewares/admin.py — IsAdmin и его тесты
(tests/test_security.py) остаются нетронутыми."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.database.models import Permission, StaffMember
from app.services.authorization import AuthorizationService


class IsStaff(BaseFilter):
    """Верхний гейт всего админ-роутера (заменяет IsAdmin там): пропускает
    платформенного оператора или любого активного сотрудника арендатора.
    Какой именно раздел доступен — решает RequirePermission на под-роутере."""

    async def __call__(
        self,
        event: TelegramObject,
        is_super_admin: bool = False,
        staff: StaffMember | None = None,
    ) -> bool:
        if is_super_admin:
            return True
        return staff is not None and staff.is_active


class RequirePermission(BaseFilter):
    """Гейт конкретного под-роутера — ставится один раз на файл хендлеров,
    как IsAdmin ставился один раз на весь админ-роутер (см.
    docs/RBAC_DESIGN.md §4). Тела хендлеров не меняются."""

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    async def __call__(
        self,
        event: TelegramObject,
        is_super_admin: bool = False,
        staff: StaffMember | None = None,
    ) -> bool:
        return AuthorizationService.has_permission(
            staff, self.permission, is_super_admin=is_super_admin
        )


class RequirePlatformOperator(BaseFilter):
    """Гейт платформенного роутера (Phase 8): апдейт обязан прийти от
    выделенного платформенного бота (data["is_platform_bot"], см.
    app/bot/middlewares/bot_identity.py) И от активного PlatformOperator.
    Оба условия обязательны — is_super_admin один не пропускает: обычный
    бот арендатора не должен «магически» становиться платформенным (см.
    docs/PLATFORM_CONTROL_PLANE.md)."""

    async def __call__(
        self,
        event: TelegramObject,
        is_platform_bot: bool = False,
        is_super_admin: bool = False,
    ) -> bool:
        return is_platform_bot and is_super_admin
