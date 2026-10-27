#!/bin/bash
# OpenPACS Restore Script
# Usage: ./restore.sh /path/to/db_openpacs_YYYYMMDD.sql.gz
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <backup_file.sql.gz>"
  echo "Available backups:"
  ls -lh /home/deploy/openpacs/backups/db_openpacs_*.sql.gz 2>/dev/null || echo "  No backups found"
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "ERROR: File not found: $BACKUP_FILE"
  exit 1
fi

echo "WARNING: This will REPLACE all data in the openpacs database."
echo "Backup file: $BACKUP_FILE"
echo "Press Ctrl+C to cancel, or Enter to continue..."
read

echo "Stopping backend..."
cd /home/deploy/openpacs && docker compose stop backend celery-worker

echo "Restoring database..."
gunzip -c "$BACKUP_FILE" | docker exec -i docker-postgres-1 psql -U openpacs -d openpacs

echo "Restarting services..."
docker compose start backend celery-worker

echo "Restore complete. Verify: curl http://localhost:8000/health"
