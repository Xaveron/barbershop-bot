"""Общий примитив для transaction-scoped advisory-lock'ов PostgreSQL.

Перенесено из app.services.booking (Phase 1-4: там жил как приватный
_advisory_lock_key) в Phase 6, чтобы LimitService мог использовать тот же
стабильный ключ блокировки по tenant_id, не импортируя приватное имя из
чужого модуля (см. docs/BILLING_DESIGN.md)."""

from __future__ import annotations

import uuid


def advisory_lock_key(entity_id: uuid.UUID) -> int:
    """Стабильный bigint-ключ блокировки из UUID (барбера, клиента, арендатора)."""
    return int.from_bytes(entity_id.bytes[:8], "big", signed=True)
