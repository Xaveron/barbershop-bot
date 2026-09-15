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
    bots_by_tenant: dict[uuid.UUID, Bot],
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> AsyncIOScheduler:
    """Планировщик работает в UTC; локальное время используется только для
    отображения. Phase 7: один и тот же набор задач регистрируется отдельно
    на каждого арендатора (со своим bot и своим job id) — app/scheduler/jobs.py
    не меняется, каждая задача и так принимала tenant_id явным параметром."""
    scheduler = AsyncIOScheduler(
        timezone=UTC,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )

    for tenant_id, bot in bots_by_tenant.items():
        scheduler.add_job(
            send_due_reminders,
            trigger=IntervalTrigger(seconds=60),
            id=f"send_due_reminders:{tenant_id}",
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
            id=f"complete_past_appointments:{tenant_id}",
            replace_existing=True,
            kwargs={"session_factory": session_factory, "tenant_id": tenant_id},
        )
        scheduler.add_job(
            schedule_return_reminders,
            trigger=IntervalTrigger(hours=6),
            id=f"schedule_return_reminders:{tenant_id}",
            replace_existing=True,
            kwargs={
                "session_factory": session_factory,
                "settings": settings,
                "tenant_id": tenant_id,
            },
        )
    logger.info(
        "Планировщик сконфигурирован: %s задач для %s арендатора(ов)",
        len(scheduler.get_jobs()),
        len(bots_by_tenant),
    )
    return scheduler
