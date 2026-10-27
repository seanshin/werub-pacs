#!/usr/bin/env bash
# WeRU.B PACS — 설치 후 검증(smoke). 컨테이너 상태 → 웹 종단(nginx/API/DICOMweb)
# → DIMSE C-ECHO. 읽기 전용. 설치 호스트에서 실행: bash scripts/install/verify-install.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DC="docker compose"; $DC version >/dev/null 2>&1 || DC="docker-compose"

PASS=0; FAIL=0; WARN=0
g(){ printf "  \033[32m✓\033[0m %s\n" "$*"; PASS=$((PASS+1)); }
w(){ printf "  \033[33m!\033[0m %s\n" "$*"; WARN=$((WARN+1)); }
f(){ printf "  \033[31m✗\033[0m %s\n" "$*"; FAIL=$((FAIL+1)); }
hdr(){ printf "\n\033[1m%s\033[0m\n" "$*"; }

# .env에서 포트/AET 읽기(기본값 보강)
NGINX_HTTP_PORT="$(grep -E '^NGINX_HTTP_PORT=' .env 2>/dev/null | cut -d= -f2)"; NGINX_HTTP_PORT="${NGINX_HTTP_PORT:-80}"
ORTHANC_AET="$(grep -E '^ORTHANC_AET=' .env 2>/dev/null | cut -d= -f2)"; ORTHANC_AET="${ORTHANC_AET:-OPENPACS}"
BASE="${VERIFY_BASE:-http://localhost:${NGINX_HTTP_PORT}}"

printf "\033[1m=== WeRU.B PACS 설치 검증 ===\033[0m\n  base=%s  AET=%s\n" "$BASE" "$ORTHANC_AET"

# ── 1. 컨테이너 상태 ──
hdr "1. 컨테이너 상태"
for svc in postgres redis orthanc backend celery-worker celery-beat mwl-scp hl7-listener admin werub nginx; do
  state="$($DC ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk -v s="$svc" '$1==s{print $2}')"
  case "$state" in
    running) g "$svc: running" ;;
    "") f "$svc: 없음(미기동)" ;;
    *) f "$svc: $state" ;;
  esac
done

# ── 2. 웹 종단 (nginx 경유) ──
hdr "2. 웹 종단 (nginx)"
code(){ curl -sk -o /dev/null -w "%{http_code}" --max-time 12 "$1" 2>/dev/null; }
c="$(code "$BASE/nginx-health")"; [ "$c" = 200 ] && g "nginx-health 200" || f "nginx-health → $c"
c="$(code "$BASE/pacs-api/health")"; [ "$c" = 200 ] && g "backend /pacs-api/health 200" || f "/pacs-api/health → $c"
c="$(code "$BASE/pacs-admin/")"; [[ "$c" =~ ^(200|302|307|308)$ ]] && g "admin /pacs-admin/ $c" || f "/pacs-admin/ → $c"
c="$(code "$BASE/werub-viewer/")"; [[ "$c" =~ ^(200|301|302)$ ]] && g "viewer /werub-viewer/ $c" || w "/werub-viewer/ → $c (뷰어 dist 확인)"
# DICOMweb: orthanc + nginx Basic-auth 주입 검증(빈 설치는 빈 배열 200)
c="$(code "$BASE/dicom-web/studies")"; [ "$c" = 200 ] && g "DICOMweb /dicom-web/studies 200 (Orthanc+auth 주입 OK)" || f "/dicom-web/studies → $c (ORTHANC_BASIC_AUTH 확인)"

# ── 3. 백엔드 통계 API ──
hdr "3. 백엔드 API"
if $DC exec -T backend curl -fs http://localhost:8000/api/v1/statistics >/dev/null 2>&1; then g "statistics API 응답"; else w "statistics API 무응답(권한/초기상태일 수 있음)"; fi

# ── 4. DIMSE C-ECHO (Orthanc DICOM 수신 검증) ──
# TLS 활성 시(ORTHANC_DICOM_TLS_ENABLED=true) TLS 핸드셰이크로 C-ECHO(스모크 — 체인검증은 모달리티 책임).
DTLS="$(grep -E '^ORTHANC_DICOM_TLS_ENABLED=' "$ROOT/.env" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
if [ "${DTLS:-false}" = "true" ]; then hdr "4. DIMSE C-ECHO (TLS)"; else hdr "4. DIMSE C-ECHO"; fi
ECHO_OUT="$($DC exec -T backend python - "$ORTHANC_AET" "${DTLS:-false}" <<'PY' 2>/dev/null
import sys
tls = sys.argv[2] == 'true'
try:
    from pynetdicom import AE
    from pynetdicom.sop_class import Verification
    ae = AE(); ae.add_requested_context(Verification)
    kw = {}
    if tls:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE  # 스모크: 핸드셰이크+DIMSE만 확인
        kw['tls_args'] = (ctx, None)
    a = ae.associate('orthanc', 4242, ae_title=sys.argv[1], **kw)
    if a.is_established:
        st = a.send_c_echo(); a.release()
        print('OK' if st and int(st.Status) == 0 else 'FAIL')
    else:
        print('ASSOC_FAIL')
except Exception as e:
    print('ERR:'+str(e)[:60])
PY
)"
case "$ECHO_OUT" in
  OK) [ "${DTLS:-false}" = "true" ] && g "C-ECHO OK over TLS (Orthanc DIMSE-TLS 수신 가능)" || g "C-ECHO OK (Orthanc DIMSE 수신 가능)" ;;
  *)  w "C-ECHO 미확인($ECHO_OUT) — TLS 설정/인증서 또는 Orthanc AE 설정 확인(웹 종단은 정상일 수 있음)" ;;
esac

# ── 요약 ──
hdr "결과"
printf "  PASS=%d  WARN=%d  FAIL=%d\n" "$PASS" "$WARN" "$FAIL"
if [ "$FAIL" -gt 0 ]; then printf "\033[31m설치 검증 실패 — 위 FAIL 항목 확인.\033[0m\n"; exit 1
else printf "\033[32m설치 검증 통과.\033[0m\n"; exit 0; fi
