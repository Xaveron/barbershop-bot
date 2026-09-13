"""Сборка составных текстов (FAQ, контакты) на языке пользователя."""

from __future__ import annotations

from app.bot.i18n import t
from app.config import Settings
from app.utils.text import esc

FAQ_KEYS: tuple[tuple[str, str], ...] = (
    ("faq.q1", "faq.a1"),
    ("faq.q2", "faq.a2"),
    ("faq.q3", "faq.a3"),
    ("faq.q4", "faq.a4"),
    ("faq.q5", "faq.a5"),
    ("faq.q6", "faq.a6"),
)


def faq_text(settings: Settings, lang: str) -> str:
    lines = [t("faq.title", lang) + "\n"]
    for question_key, answer_key in FAQ_KEYS:
        answer = t(
            answer_key,
            lang,
            cancel_lead=settings.cancel_min_lead_minutes,
            max_active=settings.max_active_appointments,
            horizon=settings.booking_horizon_days,
        )
        lines.append(f"<b>{esc(t(question_key, lang))}</b>\n{esc(answer)}\n")
    return "\n".join(lines)


def contacts_text(settings: Settings, schedule_lines: list[str], lang: str) -> str:
    parts = [
        f"📍 <b>{esc(settings.shop_name)}</b>",
        "",
        f"🗺 {esc(settings.shop_address)}",
        f"📞 {esc(settings.shop_phone)}",
    ]
    if settings.shop_maps_url:
        parts.append(
            f'🔗 <a href="{esc(settings.shop_maps_url)}">{esc(t("btn.open_map", lang))}</a>'
        )
    parts.extend(["", t("info.schedule_title", lang)])
    parts.extend(schedule_lines or [t("info.schedule_unknown", lang)])
    return "\n".join(parts)
