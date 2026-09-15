from __future__ import annotations

from sqlalchemy import func, select

from app.database.models import PlatformOperator, PlatformRole
from app.database.repositories.base import BaseRepository


class PlatformOperatorRepository(BaseRepository):
    """Не tenant-scoped: платформенный оператор не принадлежит арендатору."""

    async def get_by_telegram_id(self, telegram_user_id: int) -> PlatformOperator | None:
        stmt = select(PlatformOperator).where(
            PlatformOperator.telegram_user_id == telegram_user_id
        )
        return await self.session.scalar(stmt)

    async def any_exist(self) -> bool:
        return bool(await self.session.scalar(select(func.count()).select_from(PlatformOperator)))

    async def list_all(self) -> list[PlatformOperator]:
        stmt = select(PlatformOperator).order_by(PlatformOperator.created_at)
        return list(await self.session.scalars(stmt))

    async def create(
        self, *, telegram_user_id: int, role: PlatformRole, is_active: bool = True
    ) -> PlatformOperator:
        operator = PlatformOperator(
            telegram_user_id=telegram_user_id, role=role, is_active=is_active
        )
        self.session.add(operator)
        await self.session.flush()
        return operator
