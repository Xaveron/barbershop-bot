"""Переводы биллингового домена, общие для всех хендлеров.

Единая точка, где LimitKey/Feature/SubscriptionStatus превращаются в
читаемую подпись и где BillingError (app/services/billing.py) превращается
в готовый текст на языке пользователя — чтобы это не дублировалось в каждом
хендлере, который ловит билинговые ошибки (бронирование, создание
филиала/барбера/услуги, экспорт, аналитика) или рисует экран «Тариф». Сам
сервисный слой не знает о переводах (см. docs/BILLING_DESIGN.md)."""

from __future__ import annotations

from app.bot.i18n import t
from app.database.models import Feature, LimitKey, SubscriptionStatus
from app.services.billing import (
    BillingError,
    FeatureNotAvailable,
    PlanLimitExceeded,
    SubscriptionInactive,
)


def limit_label(key: LimitKey, lang: str) -> str:
    return t(f"billing.limit.{key.value}", lang)


def feature_label(feature: Feature, lang: str) -> str:
    return t(f"billing.feature.{feature.value}", lang)


def status_label(status: SubscriptionStatus, lang: str) -> str:
    return t(f"billing.status.{status.value}", lang)


def describe_billing_error(exc: BillingError, lang: str) -> str:
    if isinstance(exc, PlanLimitExceeded):
        return t(
            "billing.limit_reached",
            lang,
            limit_name=limit_label(exc.limit_key, lang),
            current=exc.current,
            maximum=exc.maximum,
        )
    if isinstance(exc, FeatureNotAvailable):
        return t(
            "billing.feature_not_available", lang, feature_name=feature_label(exc.feature, lang)
        )
    if isinstance(exc, SubscriptionInactive):
        return t("billing.subscription_inactive", lang)
    return t(exc.key, lang, **exc.params)
