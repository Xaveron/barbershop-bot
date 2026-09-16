"""RBAC: матрица ролей, платформенный SUPER_ADMIN, фильтры доступа, ресурсный уровень."""

from __future__ import annotations

import uuid

import pytest
from aiogram.types import CallbackQuery, Chat, Message
from aiogram.types import User as TgUser

from app.bot.middlewares.permissions import IsStaff, RequirePermission
from app.database.models import ROLE_PERMISSIONS, Permission, Role, StaffMember
from app.services.authorization import AuthorizationError, AuthorizationService
from tests.conftest import local


def make_staff(role: Role, *, is_active: bool = True, barber_id: uuid.UUID | None = None) -> StaffMember:
    return StaffMember(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        telegram_id=555_000,
        role=role,
        barber_id=barber_id,
        is_active=is_active,
    )


def make_message(user_id: int) -> Message:
    return Message(
        message_id=1,
        date=local(2026, 9, 15, 12, 0),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест"),
        text="/admin",
    )


def make_callback(user_id: int) -> CallbackQuery:
    message = Message(
        message_id=2,
        date=local(2026, 9, 15, 12, 0),
        chat=Chat(id=user_id, type="private"),
        from_user=TgUser(id=0, is_bot=True, first_name="Bot"),
        text="prev",
    )
    return CallbackQuery(
        id="1",
        from_user=TgUser(id=user_id, is_bot=False, first_name="Тест"),
        chat_instance="x",
        message=message,
        data="ad:services:",
    )


# --- Матрица ролей ------------------------------------------------------------
@pytest.mark.parametrize(
    "role,expected",
    [
        (Role.TENANT_OWNER, frozenset(Permission)),
        (Role.TENANT_ADMIN, frozenset(Permission) - {Permission.MANAGE_SUBSCRIPTION}),
        (
            Role.MANAGER,
            frozenset(
                {
                    Permission.VIEW_STAFF,
                    Permission.MANAGE_SERVICES,
                    Permission.MANAGE_SCHEDULE,
                    Permission.MANAGE_BOOKINGS,
                    Permission.MANAGE_CUSTOMERS,
                    Permission.VIEW_CUSTOMERS,
                    Permission.VIEW_ANALYTICS,
                }
            ),
        ),
        (Role.RECEPTIONIST, frozenset({Permission.MANAGE_BOOKINGS, Permission.VIEW_CUSTOMERS})),
        (Role.BARBER, frozenset({Permission.VIEW_CUSTOMERS})),
    ],
)
def test_role_permission_matrix(role, expected):
    assert ROLE_PERMISSIONS[role] == expected


def test_super_admin_role_cannot_be_constructed():
    """Структурная гарантия: SUPER_ADMIN не существует как значение Role,
    поэтому ни один код приложения не может записать его в StaffMember.role."""
    with pytest.raises(ValueError):
        Role("super_admin")
    assert "super_admin" not in {role.value for role in Role}


def test_tenant_admin_lacks_subscription_management():
    assert Permission.MANAGE_SUBSCRIPTION not in ROLE_PERMISSIONS[Role.TENANT_ADMIN]


def test_manager_has_view_staff_not_manage_staff():
    assert Permission.VIEW_STAFF in ROLE_PERMISSIONS[Role.MANAGER]
    assert Permission.MANAGE_STAFF not in ROLE_PERMISSIONS[Role.MANAGER]


def test_receptionist_and_barber_have_no_staff_management():
    assert not ROLE_PERMISSIONS[Role.RECEPTIONIST] & {
        Permission.MANAGE_STAFF, Permission.VIEW_STAFF
    }
    assert not ROLE_PERMISSIONS[Role.BARBER] & {Permission.MANAGE_STAFF, Permission.VIEW_STAFF}


# --- AuthorizationService -----------------------------------------------------
def test_super_admin_bypasses_every_permission_regardless_of_staff():
    for permission in Permission:
        assert AuthorizationService.has_permission(None, permission, is_super_admin=True)


def test_no_staff_row_has_no_permissions():
    for permission in Permission:
        assert not AuthorizationService.has_permission(None, permission)


def test_inactive_staff_has_no_permissions_even_as_owner():
    staff = make_staff(Role.TENANT_OWNER, is_active=False)
    for permission in Permission:
        assert not AuthorizationService.has_permission(staff, permission)


def test_require_raises_authorization_error_on_denial():
    staff = make_staff(Role.RECEPTIONIST)
    with pytest.raises(AuthorizationError) as exc:
        AuthorizationService.require(staff, Permission.MANAGE_STAFF)
    assert exc.value.key == "common.no_rights"


def test_require_passes_silently_when_permitted():
    staff = make_staff(Role.TENANT_OWNER)
    AuthorizationService.require(staff, Permission.MANAGE_SUBSCRIPTION)  # не должно бросить


# --- Ресурсный уровень: BARBER управляет только своей записью -----------------
def test_barber_can_manage_own_barber_resource_only():
    my_barber_id, other_barber_id = uuid.uuid4(), uuid.uuid4()
    staff = make_staff(Role.BARBER, barber_id=my_barber_id)
    assert AuthorizationService.can_manage_own_barber_resource(staff, my_barber_id)
    assert not AuthorizationService.can_manage_own_barber_resource(staff, other_barber_id)


def test_non_barber_role_has_no_barber_scoped_bypass():
    staff = make_staff(Role.MANAGER, barber_id=None)
    assert not AuthorizationService.can_manage_own_barber_resource(staff, uuid.uuid4())


def test_inactive_barber_loses_own_resource_access():
    barber_id = uuid.uuid4()
    staff = make_staff(Role.BARBER, barber_id=barber_id, is_active=False)
    assert not AuthorizationService.can_manage_own_barber_resource(staff, barber_id)


# --- IsStaff / RequirePermission (фильтры на реальных Telegram-объектах) -----
# Phase 8: оба фильтра больше не читают Settings/ADMIN_ID сами — is_super_admin
# приходит DI-инъекцией (см. app/bot/middlewares/staff.py, вычисляется через
# PlatformAuthorizationService). Здесь передаём его напрямую, как и любой
# другой параметр из data.
async def test_is_staff_allows_platform_super_admin():
    assert await IsStaff()(make_message(111111), is_super_admin=True, staff=None)


async def test_is_staff_allows_active_tenant_staff():
    staff = make_staff(Role.RECEPTIONIST)
    assert await IsStaff()(make_message(999999), is_super_admin=False, staff=staff)


async def test_is_staff_denies_inactive_staff():
    staff = make_staff(Role.RECEPTIONIST, is_active=False)
    assert not await IsStaff()(make_message(999999), is_super_admin=False, staff=staff)


async def test_is_staff_denies_stranger():
    assert not await IsStaff()(make_message(999999), is_super_admin=False, staff=None)


async def test_require_permission_ignores_is_admin_display_flag():
    """Регрессия: is_admin в data — это только флаг показа кнопки, а не
    источник авторизации. RequirePermission обязан смотреть исключительно на
    is_super_admin и на реальный staff, а не на этот флаг."""
    filter_ = RequirePermission(Permission.MANAGE_STAFF)
    # `is_admin=True` нарочно НЕ передаётся фильтру — у него нет такого
    # параметра. Проверяем, что без is_super_admin и без staff отказ
    # происходит независимо от того, что где-то в data мог быть True.
    assert not await filter_(make_callback(999999), is_super_admin=False, staff=None)


async def test_require_permission_allows_super_admin_for_any_permission():
    for permission in Permission:
        assert await RequirePermission(permission)(
            make_callback(111111), is_super_admin=True, staff=None
        )


async def test_require_permission_denies_role_without_that_permission():
    staff = make_staff(Role.RECEPTIONIST)
    assert not await RequirePermission(Permission.MANAGE_STAFF)(
        make_callback(999999), is_super_admin=False, staff=staff
    )


async def test_require_permission_allows_role_with_that_permission():
    staff = make_staff(Role.RECEPTIONIST)
    assert await RequirePermission(Permission.MANAGE_BOOKINGS)(
        make_callback(999999), is_super_admin=False, staff=staff
    )
