#!/usr/bin/env bash
# Generate .env from .env.example with strong random secrets + derived values.
# Idempotent guard: refuses to overwrite an existing .env (move it aside first).
# Usage: bash scripts/install/gen-secrets.sh [dest .env path]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/.env.example"
DST="${1:-$ROOT/.env}"

[ -f "$SRC" ] || { echo "ERROR: $SRC 없음" >&2; exit 1; }
[ -f "$DST" ] && { echo "ERROR: $DST 이미 존재 — 덮어쓰지 않음(필요시 백업 후 삭제)" >&2; exit 1; }
command -v openssl >/dev/null || { echo "ERROR: openssl 필요" >&2; exit 1; }

# 영숫자 비밀번호 N자
rnd(){ openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }

PG_USER="openpacs"; PG_DB="openpacs"; ORTHANC_USER="admin"
PG_PW="$(rnd 28)"; REDIS_PW="$(rnd 24)"; ORTHANC_PW="$(rnd 20)"
SECRET="$(rnd 48)"; GRAFANA_PW="$(rnd 20)"
EXPORT_SECRET="$(openssl rand -hex 32)"
BASIC_AUTH="$(printf '%s:%s' "$ORTHANC_USER" "$ORTHANC_PW" | base64 | tr -d '\n')"

cp "$SRC" "$DST"
sedi(){ sed -i.bak "s|^$1=.*|$1=$2|" "$DST" && rm -f "$DST.bak"; }

sedi POSTGRES_USER "$PG_USER"
sedi POSTGRES_DB "$PG_DB"
sedi POSTGRES_PASSWORD "$PG_PW"
sedi REDIS_PASSWORD "$REDIS_PW"
sedi ORTHANC_USERNAME "$ORTHANC_USER"
sedi ORTHANC_PASSWORD "$ORTHANC_PW"
sedi ORTHANC_BASIC_AUTH "$BASIC_AUTH"
sedi SECRET_KEY "$SECRET"
sedi GRAFANA_ADMIN_PASSWORD "$GRAFANA_PW"
sedi PATIENT_EXPORT_SECRET "$EXPORT_SECRET"
# compose builds DATABASE_URL from POSTGRES_*, but keep .env consistent (service-name host)
sedi DATABASE_URL "postgresql+asyncpg://$PG_USER:$PG_PW@postgres:5432/$PG_DB"

chmod 600 "$DST" 2>/dev/null || true
echo "✓ $DST 생성(랜덤 시크릿). 남은 CHANGE_ME(AI 키 등 선택)와 기관값(INSTITUTION_NAME/BASE_URL)을 검토하세요."
# 남은 CHANGE_ME 경고
if grep -q "CHANGE_ME" "$DST"; then
  echo "  ⚠ 미설정(CHANGE_ME) 항목:"; grep -n "CHANGE_ME" "$DST" | sed 's/^/    /'
fi
