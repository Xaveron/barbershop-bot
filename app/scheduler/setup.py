"""Конфигурация APScheduler."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.scheduler.jobs import (
    complete_past_appointments,
    schedule_return_reminders,
    send_due_reminders,
)

logger = logging.getLogger(__name__)


def build_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    tenant_id: uuid.UUID,
) -> AsyncIOScheduler:
    """Планировщик работает в UTC; локальное время используется только для отображения."""
    scheduler = AsyncIOScheduler(
        timezone=UTC,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )

    scheduler.add_job(
        send_due_reminders,
        trigger=IntervalTrigger(seconds=60),
        id="send_due_reminders",
        replace_existing=True,
        kwargs={
            "bot": bot,
            "session_factory": session_factory,
            "settings": settings,
            "tenant_id": tenant_id,
        },
    )
    scheduler.add_job(
        complete_past_appointments,
        trigger=IntervalTrigger(minutes=30),
        id="complete_past_appointments",
        replace_existing=True,
        kwargs={"session_factory": session_factory, "tenant_id": tenant_id},
    )
    scheduler.add_job(
        schedule_return_reminders,
        trigger=IntervalTrigger(hours=6),
        id="schedule_return_reminders",
        replace_existing=True,
        kwargs={"session_factory": session_factory, "settings": settings, "tenant_id": tenant_id},
    )
    logger.info("Планировщик сконфигурирован: %s задач", len(scheduler.get_jobs()))
    return scheduler
