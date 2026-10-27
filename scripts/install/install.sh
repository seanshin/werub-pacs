#!/usr/bin/env bash
# WeRU.B PACS — 단일 기관 설치 (멱등). 정본 docker-compose.yml 기준.
#   bash scripts/install/install.sh
# 환경변수(선택): ADMIN_USERNAME, ADMIN_PASSWORD, SKIP_PREFLIGHT=1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
say(){ printf "\n\033[1m== %s ==\033[0m\n" "$*"; }

DC="docker compose"
$DC version >/dev/null 2>&1 || DC="docker-compose"

# 1. 전제조건
say "1/6 전제조건 점검"
if [ "${SKIP_PREFLIGHT:-0}" = "1" ]; then echo "  (SKIP_PREFLIGHT=1 — 건너뜀)"
else bash scripts/install/preflight.sh || { echo "전제조건 FAIL — 해결 후 재실행(또는 SKIP_PREFLIGHT=1)."; exit 1; }
fi

# 2. .env (시크릿 생성 + 기관값)
say "2/6 환경설정(.env)"
if [ -f .env ]; then
  echo "  .env 이미 존재 — 그대로 사용"
else
  bash scripts/install/gen-secrets.sh
  read -rp "  기관명 [WeRU.B PACS]: " inst || true
  [ -n "${inst:-}" ] && { sed -i.bak "s|^INSTITUTION_NAME=.*|INSTITUTION_NAME=$inst|" .env && rm -f .env.bak; }
  read -rp "  공개 도메인 URL [https://pacs.example.org]: " burl || true
  if [ -n "${burl:-}" ]; then
    sed -i.bak "s|^BASE_URL=.*|BASE_URL=$burl|; s|^PREFETCH_WARM_BASE_URL=.*|PREFETCH_WARM_BASE_URL=$burl|" .env && rm -f .env.bak
  fi
fi

# 3. 빌드
say "3/6 이미지 빌드"
$DC build

# 4. 기동 (스키마는 backend startup 마이그레이션 러너가 생성)
say "4/6 서비스 기동"
$DC up -d

# 5. 백엔드 헬스 대기
say "5/6 백엔드 기동 대기"
ok=0
for i in $(seq 1 60); do
  if $DC exec -T backend curl -fs http://localhost:8000/health >/dev/null 2>&1; then ok=1; echo "  backend healthy"; break; fi
  sleep 3
done
[ "$ok" = 1 ] || { echo "  backend health 타임아웃 — 로그:"; $DC logs backend | tail -40; exit 1; }

# 6. 첫 관리자
say "6/6 첫 관리자 계정"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
GEN_PW=0
if [ -z "${ADMIN_PASSWORD:-}" ]; then
  ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 16)"; GEN_PW=1
fi
$DC exec -T -e ADMIN_PASSWORD="$ADMIN_PASSWORD" backend \
  python -m app.scripts.create_admin --username "$ADMIN_USERNAME"

# 기관 기본값 시드(멱등) — DICOM 검증 규칙/모달리티/메시지
$DC exec -T backend python -m app.scripts.seed_institution || echo "  (시드 경고 — 첫 접근 시 자동 시드됨)"

# 설치 검증(smoke) — 실패해도 설치 자체는 진행됨(정보용)
say "검증(smoke)"
bash scripts/install/verify-install.sh || echo "  (검증 경고 — 위 항목 점검)"

printf "\n\033[32m설치 완료.\033[0m\n"
echo "  접속:   https://<도메인>/pacs-admin"
if [ "$GEN_PW" = 1 ]; then
  echo "  관리자: ${ADMIN_USERNAME}  /  ${ADMIN_PASSWORD}"
  echo "  ⚠ 위 비밀번호를 안전히 보관하고 첫 로그인 후 변경하세요."
else
  echo "  관리자: ${ADMIN_USERNAME}"
fi
cat <<'EOF'
  다음(권장):
   - TLS 인증서 배치(docker/nginx/certs) 및 템플릿 HTTPS 블록 활성화
   - 모달리티/외부 PACS AE 등록(관리자 → 외부연동)
   - 모니터링 필요 시: docker compose --profile monitoring up -d
   - 정기 백업 cron 가동(scripts/server/backup-openpacs.sh)
EOF
