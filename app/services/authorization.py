"""Централизованная авторизация: роль/право, а не разбросанные if user.is_admin."""

from __future__ import annotations

import uuid

from app.database.models import ROLE_PERMISSIONS, Permission, Role, StaffMember


class AuthorizationError(Exception):
    """Аналог BookingError (app/services/booking.py): несёт ключ перевода,
    а не готовый текст — хендлер сам решает, как ответить на языке юзера."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class AuthorizationService:
    @staticmethod
    def has_permission(
        staff: StaffMember | None, permission: Permission, *, is_super_admin: bool = False
    ) -> bool:
        if is_super_admin:
            return True
        if staff is None or not staff.is_active:
            return False
        return permission in ROLE_PERMISSIONS.get(staff.role, frozenset())

    @staticmethod
    def require(
        staff: StaffMember | None, permission: Permission, *, is_super_admin: bool = False
    ) -> None:
        allowed = AuthorizationService.has_permission(
            staff, permission, is_super_admin=is_super_admin
        )
        if not allowed:
            raise AuthorizationError("common.no_rights")

    @staticmethod
    def can_manage_own_barber_resource(staff: StaffMember | None, barber_id: uuid.UUID) -> bool:
        """Ресурсный уровень (см. docs/RBAC_DESIGN.md §6): BARBER управляет
        только своей записью-барбером, а не любой в своём арендаторе.

        Не вызывается ни одним хендлером в Phase 2 — в приложении нет флоу,
        где барбер сам авторизуется в боте (Barber.telegram_id не используется
        нигде). Существует и тестируется как готовый примитив для будущей
        фазы: та комбинировала бы это с has_permission(MANAGE_SCHEDULE) для
        ролей, у которых доступ не сужен до «только своё»."""
        if staff is None or not staff.is_active or staff.role != Role.BARBER:
            return False
        return staff.barber_id == barber_id

    @staticmethod
    def can_access_branch(
        staff: StaffMember | None,
        branch_id: uuid.UUID,
        *,
        accessible_branch_ids: frozenset[uuid.UUID],
        is_super_admin: bool = False,
    ) -> bool:
        """4-я независимая проверка (см. docs/BRANCHES_DESIGN.md), отдельно
        от tenant isolation / authorization / resource ownership: «может ли
        сотрудник вообще трогать этот филиал». TENANT_OWNER/TENANT_ADMIN
        видят все филиалы своего арендатора без единой строки staff_branches;
        остальным ролям нужна явная запись.

        accessible_branch_ids — уже прочитанный набор
        (BranchRepository.accessible_branch_ids_for_staff), а не запрос
        внутри этого метода: сервис остаётся чистой функцией без I/O, как и
        его соседи, а поход в БД вызывающий код делает один раз за хендлер."""
        if is_super_admin:
            return True
        if staff is None or not staff.is_active:
            return False
        if staff.role in (Role.TENANT_OWNER, Role.TENANT_ADMIN):
            return True
        return branch_id in accessible_branch_ids
