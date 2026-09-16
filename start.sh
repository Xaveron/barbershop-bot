#!/bin/bash

set -e

cd "$(dirname "$0")"

echo "=================================="
echo "   BARBERSHOP BOT — START"
echo "=================================="

# Проверяем Docker
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Docker не установлен."
    exit 1
fi

# Проверяем Docker Compose
if ! docker compose version >/dev/null 2>&1; then
    echo "❌ Docker Compose не найден."
    exit 1
fi

# Создаём .env из шаблона, если его нет
if [ ! -f .env ]; then
    echo "⚠️ Файл .env отсутствует."
    echo "Создаю его из .env.example..."
    cp .env.example .env
    echo ""
    echo "❗ Заполни BOT_TOKEN и ADMIN_ID в .env"
    echo "После этого запусти start.sh ещё раз."
    exit 1
fi

echo "🐳 Запускаю Docker..."
echo ""

docker compose up --build
