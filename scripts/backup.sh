#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-$HOME/family-meal-planner}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%F)"

mkdir -p "$BACKUP_DIR"
cd "$COMPOSE_DIR"

docker compose exec -T mealie-db pg_dump -U mealie --no-owner --no-privileges mealie \
  | gzip > "$BACKUP_DIR/mealie-db-$STAMP.sql.gz"

if docker compose ps --services --filter "status=running" | grep -q "^planner-db$"; then
  docker compose exec -T planner-db pg_dump -U planner --no-owner --no-privileges planner \
    | gzip > "$BACKUP_DIR/planner-db-$STAMP.sql.gz"
fi

docker run --rm \
  -v family-meal-planner_mealie-data:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine tar czf "/backup/mealie-data-$STAMP.tar.gz" -C /data .

find "$BACKUP_DIR" -name '*.gz' -mtime +"$RETENTION_DAYS" -delete
echo "Backup completed: $STAMP"
