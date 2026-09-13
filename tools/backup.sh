#!/usr/bin/env bash
# Резервная копия базы барбершопа.
#
# Запуск вручную:      ./tools/backup.sh
# Ежедневно в 03:30:   30 3 * * * /path/to/barbershop_bot/tools/backup.sh >> /var/log/barbershop-backup.log 2>&1
#
# Переменные (можно задать в .env или в окружении):
#   BACKUP_DIR      куда складывать дампы (по умолчанию ./backups)
#   BACKUP_KEEP     сколько дампов хранить (по умолчанию 14)
#   DB_SERVICE      имя сервиса PostgreSQL в docker compose (по умолчанию db)
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
DB_SERVICE="${DB_SERVICE:-db}"
POSTGRES_USER="${POSTGRES_USER:-barber}"
POSTGRES_DB="${POSTGRES_DB:-barbershop}"

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="$BACKUP_DIR/barbershop_$STAMP.sql.gz"

docker compose exec -T "$DB_SERVICE" \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists \
  | gzip > "$TARGET"

# Пустой или обрезанный дамп хуже отсутствующего — проверяем целостность архива.
gzip -t "$TARGET"
SIZE=$(wc -c < "$TARGET")
if [ "$SIZE" -lt 1024 ]; then
  echo "Дамп подозрительно мал ($SIZE байт): $TARGET" >&2
  exit 1
fi

# Ротация: оставляем последние BACKUP_KEEP файлов.
ls -1t "$BACKUP_DIR"/barbershop_*.sql.gz | tail -n "+$((BACKUP_KEEP + 1))" | xargs -r rm --

echo "OK: $TARGET ($SIZE байт)"
echo "Восстановление: gunzip -c $TARGET | docker compose exec -T $DB_SERVICE psql -U $POSTGRES_USER -d $POSTGRES_DB"
