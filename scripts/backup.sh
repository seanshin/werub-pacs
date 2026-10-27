#!/bin/bash
# OpenPACS Daily Backup Script
# Run via cron: 0 2 * * * /home/deploy/openpacs/scripts/backup.sh
set -e

BACKUP_DIR="/home/deploy/openpacs/backups"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=30

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting OpenPACS backup..."

# 1. PostgreSQL backup
echo "  Backing up PostgreSQL (openpacs DB)..."
docker exec docker-postgres-1 pg_dump -U openpacs openpacs | gzip > "$BACKUP_DIR/pg_openpacs_$DATE.sql.gz"
echo "  PostgreSQL backup: $(du -h "$BACKUP_DIR/pg_openpacs_$DATE.sql.gz" | cut -f1)"

# 2. Orthanc DICOM storage backup
echo "  Backing up Orthanc DICOM storage..."
ORTHANC_VOL=$(docker volume inspect openpacs_orthanc-db --format '{{.Mountpoint}}' 2>/dev/null)
if [ -n "$ORTHANC_VOL" ]; then
    tar czf "$BACKUP_DIR/orthanc_storage_$DATE.tar.gz" -C "$ORTHANC_VOL" . 2>/dev/null
    echo "  Orthanc backup: $(du -h "$BACKUP_DIR/orthanc_storage_$DATE.tar.gz" | cut -f1)"
else
    echo "  Orthanc volume not found, skipping"
fi

# 3. Config files backup
echo "  Backing up config files..."
tar czf "$BACKUP_DIR/config_$DATE.tar.gz" \
    /home/deploy/openpacs/docker-compose.yml \
    /home/deploy/openpacs/viewer/app-config.js \
    /etc/nginx/sites-enabled/hospital-run \
    2>/dev/null
echo "  Config backup done"

# 4. Cleanup old backups
echo "  Cleaning up backups older than $KEEP_DAYS days..."
find "$BACKUP_DIR" -name "*.gz" -mtime +$KEEP_DAYS -delete 2>/dev/null
TOTAL=$(du -sh "$BACKUP_DIR" | cut -f1)
COUNT=$(ls -1 "$BACKUP_DIR"/*.gz 2>/dev/null | wc -l)

echo "[$(date)] Backup complete: $COUNT files, $TOTAL total"
