"""Экспорт записей в CSV."""

from __future__ import annotations

import csv
import io
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
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tz = settings.tz
        self.appointments = AppointmentRepository(session)

    async def appointments_csv(self, *, start: datetime, end: datetime) -> bytes:
        rows = await self.appointments.list_for_export(start=start, end=end)
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_HEADERS)
        for appointment, user, barber, service in rows:
            local = to_local(appointment.starts_at, self.tz)
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
                    to_local(appointment.created_at, self.tz).strftime("%Y-%m-%d %H:%M"),
                )
            )
        # BOM — чтобы Excel корректно открыл UTF-8 с кириллицей.
        return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
