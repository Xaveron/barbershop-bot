"""Фильтры доступа к разделам админ-панели: платформенный SUPER_ADMIN
(ADMIN_ID, как и раньше) либо активный StaffMember арендатора с нужным
правом. Отдельно от app/bot/middlewares/admin.py — IsAdmin и его тесты
(tests/test_security.py) остаются нетронутыми."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.config import Settings
from app.database.models import Permission, StaffMember
from app.services.authorization import AuthorizationService


def _is_super_admin(event: TelegramObject, settings: Settings | None) -> bool:
    if settings is None:
        return False
    user = getattr(event, "from_user", None)
    return user is not None and settings.is_admin(user.id)


class IsStaff(BaseFilter):
    """Верхний гейт всего админ-роутера (заменяет IsAdmin там): пропускает
    платформенного SUPER_ADMIN или любого активного сотрудника арендатора.
    Какой именно раздел доступен — решает RequirePermission на под-роутере."""

    async def __call__(
        self,
        event: TelegramObject,
        settings: Settings | None = None,
        staff: StaffMember | None = None,
    ) -> bool:
        if _is_super_admin(event, settings):
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
        settings: Settings | None = None,
        staff: StaffMember | None = None,
    ) -> bool:
        is_super_admin = _is_super_admin(event, settings)
        return AuthorizationService.has_permission(
            staff, self.permission, is_super_admin=is_super_admin
        )
