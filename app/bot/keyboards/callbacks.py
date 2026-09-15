"""Фабрики callback_data.

Лимит Telegram — 64 байта, поэтому в callback передаётся максимум один UUID,
а остальной контекст хранится в FSM-состоянии.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCB(CallbackData, prefix="m"):
    action: str  # main | book | my | services | barbers | contacts | faq


class BranchCB(CallbackData, prefix="bh"):
    id: str


class ServiceCB(CallbackData, prefix="sv"):
    id: str


class BarberCB(CallbackData, prefix="br"):
    id: str


class DayCB(CallbackData, prefix="dt"):
    value: str  # YYYY-MM-DD


class TimeCB(CallbackData, prefix="tm"):
    value: str  # HHMM


class ConfirmCB(CallbackData, prefix="cf"):
    action: str  # yes | no


class NavCB(CallbackData, prefix="nv"):
    to: str  # main | service | barber | day | my | admin


class ApptCB(CallbackData, prefix="ap"):
    action: str  # view | cancel | cancel_ok | move
    id: str


class LangCB(CallbackData, prefix="lg"):
    code: str


class AdmCB(CallbackData, prefix="ad"):
    action: str
    arg: str = ""


class AdmDayCB(CallbackData, prefix="aw"):
    barber: str
    weekday: int


class OnbCB(CallbackData, prefix="ob"):
    action: str  # welcome | skip_tz | skip_currency | activate | ...


class PlatformCB(CallbackData, prefix="pf"):
    """Только выделенный платформенный бот (data["is_platform_bot"]) когда-либо
    доходит до роутера, который читает эти callback — но arg всё равно
    сервер-сайд валидируется на каждый апдейт (см. docs/PLATFORM_CONTROL_PLANE.md
    §Callback security): arg НИКОГДА не доверяется напрямую."""

    action: str  # menu | tenants | tenant | create | activate | suspend | bots | bot_toggle
    arg: str = ""
