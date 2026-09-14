"""Наполнение базы стартовыми данными: `python -m app.seed`.

Скрипт идемпотентен — повторный запуск ничего не дублирует.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import time
from decimal import Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import build_engine, build_session_factory, wait_for_database
from app.database.models import Barber, Service, WorkingSchedule
from app.utils.logging import mask_secrets, setup_logging

logger = logging.getLogger(__name__)

DEFAULT_SERVICES: tuple[dict[str, object], ...] = (
    {
        "name": "Мужская стрижка",
        "duration_minutes": 60,
        "price": Decimal("250.00"),
        "description": "Классическая или модельная стрижка машинкой и ножницами.",
        "sort_order": 10,
    },
    {
        "name": "Стрижка бороды",
        "duration_minutes": 30,
        "price": Decimal("150.00"),
        "description": "Моделирование бороды, окантовка, уход.",
        "sort_order": 20,
    },
    {
        "name": "Стрижка + борода",
        "duration_minutes": 90,
        "price": Decimal("350.00"),
        "description": "Комплекс: стрижка и оформление бороды.",
        "sort_order": 30,
    },
    {
        "name": "Детская стрижка",
        "duration_minutes": 45,
        "price": Decimal("200.00"),
        "description": "Для гостей до 12 лет.",
        "sort_order": 40,
    },
)

DEFAULT_BARBERS: tuple[dict[str, object], ...] = (
    {"name": "Иван", "description": "Классические стрижки, фейды.", "sort_order": 10},
    {"name": "Артём", "description": "Бороды, горячее бритьё.", "sort_order": 20},
)

# Пн–Пт 10:00–19:00, Сб 10:00–16:00, Вс — выходной.
DEFAULT_WEEK: dict[int, tuple[time, time]] = {
    0: (time(10, 0), time(19, 0)),
    1: (time(10, 0), time(19, 0)),
    2: (time(10, 0), time(19, 0)),
    3: (time(10, 0), time(19, 0)),
    4: (time(10, 0), time(19, 0)),
    5: (time(10, 0), time(16, 0)),
}


async def seed() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    try:
        engine = build_engine(settings.database_url)
        session_factory = build_session_factory(engine)
        await wait_for_database(engine)
    except Exception as exc:
        logger.error("Не удалось подключиться к базе данных: %s", mask_secrets(str(exc)))
        return

    async with session_factory() as session:
        for payload in DEFAULT_SERVICES:
            exists = await session.scalar(select(Service).where(Service.name == payload["name"]))
            if exists is None:
                session.add(Service(**payload, currency=settings.default_currency))
                logger.info("Добавлена услуга: %s", payload["name"])

        for payload in DEFAULT_BARBERS:
            barber = await session.scalar(select(Barber).where(Barber.name == payload["name"]))
            if barber is None:
                barber = Barber(**payload)
                session.add(barber)
                await session.flush()
                logger.info("Добавлен барбер: %s", payload["name"])

            for weekday, (start, end) in DEFAULT_WEEK.items():
                schedule_exists = await session.scalar(
                    select(WorkingSchedule).where(
                        WorkingSchedule.barber_id == barber.id,
                        WorkingSchedule.weekday == weekday,
                    )
                )
                if schedule_exists is None:
                    session.add(
                        WorkingSchedule(
                            barber_id=barber.id,
                            weekday=weekday,
                            start_time=start,
                            end_time=end,
                        )
                    )

        await session.commit()

    await engine.dispose()
    logger.info("Стартовые данные готовы")


if __name__ == "__main__":
    asyncio.run(seed())
