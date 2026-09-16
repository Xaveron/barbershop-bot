"""Экспорт записей в CSV."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Collection
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.repositories import AppointmentRepository
from app.utils.dt import to_local
from app.utils.text import csv_safe

CSV_HEADERS = (
    "id",
    "дата",
    "время",
    "статус",
    "услуга",
    "барбер",
    "клиент",
    "telegram_id",
    "username",
    "телефон",
    "длительность_мин",
    "цена",
    "валюта",
    "создана",
)


class ExportService:
    """Каждая строка форматируется в часовом поясе ЕЁ филиала
    (appointment.branch.tz — authoritative, см. §H-3 Phase 9B), не в едином
    settings.tz: CSV из нескольких филиалов в разных зонах может содержать
    строки с разным локальным временем для одного и того же UTC-момента."""

    def __init__(self, session: AsyncSession, settings: Settings, tenant_id: uuid.UUID) -> None:
        self.session = session
        self.settings = settings
        self.appointments = AppointmentRepository(session, tenant_id)

    async def appointments_csv(
        self,
        *,
        start: datetime,
        end: datetime,
        branch_ids: Collection[uuid.UUID] | None = None,
    ) -> bytes:
        """branch_ids=None — без ограничений; иначе — только доступные
        сотруднику филиалы (см. §C-1, Phase 9A). start/end — обычный
        UTC-диапазон периода экспорта (7/30/90 дней/всё), не календарный
        день/месяц — branch-local здесь касается только форматирования
        колонок "дата"/"время"/"создана" для каждой строки."""
        rows = await self.appointments.list_for_export(
            start=start, end=end, branch_ids=branch_ids
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_HEADERS)
        for appointment, user, barber, service in rows:
            branch_tz = appointment.branch.tz
            local = to_local(appointment.starts_at, branch_tz)
            writer.writerow(
                (
                    str(appointment.id),
                    local.strftime("%Y-%m-%d"),
                    local.strftime("%H:%M"),
                    appointment.status.value,
                    csv_safe(service.name),
                    csv_safe(barber.name),
                    csv_safe(user.full_name),
                    user.telegram_id,
                    csv_safe(user.username or ""),
                    csv_safe(user.phone or ""),
                    appointment.duration_minutes,
                    f"{appointment.price:.2f}",
                    appointment.currency,
                    to_local(appointment.created_at, branch_tz).strftime("%Y-%m-%d %H:%M"),
                )
            )
        # BOM — чтобы Excel корректно открыл UTF-8 с кириллицей.
        return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
