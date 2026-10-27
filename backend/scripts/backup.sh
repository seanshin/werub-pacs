#!/bin/bash
# OpenPACS Daily Backup Script
# Usage: 0 3 * * * /home/deploy/openpacs/backend/scripts/backup.sh
set -e

BACKUP_DIR="/home/deploy/openpacs/backups"
RETENTION_DAYS=7
DATE=$(date +%Y%m%d_%H%M%S)
LOG_PREFIX="[backup $DATE]"

mkdir -p "$BACKUP_DIR"

echo "$LOG_PREFIX Starting backup..."

# 1. PostgreSQL dump
echo "$LOG_PREFIX Dumping PostgreSQL..."
docker exec docker-postgres-1 pg_dump -U openpacs -d openpacs \
  --no-owner --no-privileges \
  | gzip > "$BACKUP_DIR/db_openpacs_$DATE.sql.gz"

DB_SIZE=$(du -h "$BACKUP_DIR/db_openpacs_$DATE.sql.gz" | cut -f1)
echo "$LOG_PREFIX DB dump: $DB_SIZE"

# 2. Orthanc data (index only, DICOM files are in Docker volume)
echo "$LOG_PREFIX Backing up Orthanc index..."
docker exec docker-postgres-1 pg_dump -U openpacs -d openpacs \
  -t 'attachedfiles' -t 'changes' -t 'dicomidentifiers' \
  -t 'exportedresources' -t 'globalintegers*' -t 'globalproperties' \
  -t 'labels' -t 'maindicomtags' -t 'metadata' -t 'resources' \
  --no-owner --no-privileges \
  | gzip > "$BACKUP_DIR/orthanc_index_$DATE.sql.gz"

# 3. Configuration files
echo "$LOG_PREFIX Backing up configs..."
tar czf "$BACKUP_DIR/configs_$DATE.tar.gz" \
  /home/deploy/openpacs/docker-compose.yml \
  /home/deploy/openpacs/backend/alembic.ini \
  /home/deploy/openpacs/werub-viewer/config/ \
  /etc/nginx/sites-enabled/hospital-run \
  2>/dev/null || true

# 4. Cleanup old backups
echo "$LOG_PREFIX Cleaning backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "*.gz" -mtime +$RETENTION_DAYS -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +$RETENTION_DAYS -delete

TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
FILE_COUNT=$(ls -1 "$BACKUP_DIR" | wc -l)

echo "$LOG_PREFIX Backup complete. $FILE_COUNT files, $TOTAL_SIZE total."
