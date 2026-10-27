#!/usr/bin/env bash
# WeRU.B PACS — 설치 전제조건 점검 (preflight)
# 읽기 전용: 시스템을 변경하지 않고 설치 가능 여부만 진단한다.
# 사용: bash scripts/install/preflight.sh   (sudo 불필요, 일부 항목은 권한에 따라 WARN)
set -uo pipefail

# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────
PASS=0; WARN=0; FAIL=0
g(){ printf "  \033[32m✓ PASS\033[0m  %s\n" "$*"; PASS=$((PASS+1)); }
w(){ printf "  \033[33m! WARN\033[0m  %s\n" "$*"; WARN=$((WARN+1)); }
f(){ printf "  \033[31m✗ FAIL\033[0m  %s\n" "$*"; FAIL=$((FAIL+1)); }
hdr(){ printf "\n\033[1m%s\033[0m\n" "$*"; }
has(){ command -v "$1" >/dev/null 2>&1; }

# 요구 최소치 (필요 시 조정)
MIN_CPU=4
MIN_RAM_GB=8
MIN_DISK_GB=100          # DICOM 저장 파티션 권장 여유
DICOM_PATH="${DICOM_PATH:-/var/lib/openpacs}"   # 실제 영상 저장 경로(설치 시 지정)

printf "\033[1m=== WeRU.B PACS 설치 전제조건 점검 ===\033[0m\n"
printf "host=%s  date=%s\n" "$(hostname 2>/dev/null || echo ?)" "$(date '+%F %T %Z' 2>/dev/null)"

# ── 1. OS / 커널 ─────────────────────────────────────────────────────────────
hdr "1. 운영체제 / 커널"
OS="$(uname -s)"
if [ "$OS" = "Linux" ]; then
  g "Linux ($(uname -r))"
  if [ -r /etc/os-release ]; then . /etc/os-release; printf "        배포판: %s\n" "${PRETTY_NAME:-?}"; fi
else
  w "비-Linux ($OS) — 운영은 Linux 권장(개발/평가는 가능)"
fi
case "$(uname -m)" in
  x86_64|amd64) g "아키텍처 x86_64" ;;
  aarch64|arm64) w "ARM64 — 일부 이미지(orthanc 등) 멀티아치 확인 필요" ;;
  *) w "아키텍처 $(uname -m) — 이미지 호환 확인" ;;
esac

# ── 2. Docker / Compose ──────────────────────────────────────────────────────
hdr "2. Docker / Compose"
if has docker; then
  g "docker 설치됨 ($(docker --version 2>/dev/null | sed 's/Docker version //'))"
  if docker info >/dev/null 2>&1; then g "docker 데몬 동작 + 현재 사용자 접근 가능"
  else f "docker 데몬 미동작 또는 권한 없음 (sudo 또는 docker 그룹 필요)"; fi
else
  f "docker 미설치 — Docker Engine 설치 필요"
fi
if docker compose version >/dev/null 2>&1; then g "docker compose v2 ($(docker compose version --short 2>/dev/null))"
elif has docker-compose; then w "docker-compose v1 — v2(plugin) 권장"
else f "docker compose 미설치"; fi

# ── 3. 포트 충돌 ─────────────────────────────────────────────────────────────
hdr "3. 포트 가용성 (이미 점유 시 설치 충돌)"
port_in_use(){
  local p="$1"
  if has ss; then ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${p}\$"
  elif has netstat; then netstat -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${p}\$"
  elif has lsof; then lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1
  else return 2; fi
}
# 공개(외부) 포트 — 충돌 시 FAIL / 내부(127.0.0.1) 바인딩 — 충돌 시 WARN
declare -a PUBLIC=("80:HTTP" "443:HTTPS" "4242:DICOM C-STORE" "4243:MWL SCP" "2575:HL7 MLLP")
declare -a LOCAL=("5432:PostgreSQL" "6379:Redis" "8042:Orthanc HTTP" "8000:Backend" "8001:Backend" "3001:OHIF/Admin" "3004:WeRU.B Viewer" "3000:Grafana" "9090:Prometheus" "8080:Keycloak")
for e in "${PUBLIC[@]}"; do p="${e%%:*}"; n="${e#*:}"
  if port_in_use "$p"; then f "포트 $p ($n) 점유됨 — 해제 필요"; else g "포트 $p ($n) 가용"; fi; done
for e in "${LOCAL[@]}"; do p="${e%%:*}"; n="${e#*:}"
  if port_in_use "$p"; then w "포트 $p ($n) 점유됨 — 기존 서비스와 충돌 가능"; else g "포트 $p ($n) 가용"; fi; done

# ── 4. CPU / 메모리 / 디스크 ─────────────────────────────────────────────────
hdr "4. 자원 (CPU / RAM / 디스크)"
CPU="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
[ "$CPU" -ge "$MIN_CPU" ] 2>/dev/null && g "CPU ${CPU} 코어 (>= ${MIN_CPU})" || w "CPU ${CPU} 코어 — ${MIN_CPU}+ 권장(AI/뷰어 동시부하)"
RAM_GB=""
if [ -r /proc/meminfo ]; then RAM_GB=$(awk '/MemTotal/{printf "%d", $2/1024/1024}' /proc/meminfo)
elif has sysctl && sysctl -n hw.memsize >/dev/null 2>&1; then RAM_GB=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 )); fi
if [ -z "$RAM_GB" ]; then w "RAM 측정불가(비-Linux) — Linux 설치 호스트에서 재점검"
elif [ "$RAM_GB" -ge "$MIN_RAM_GB" ] 2>/dev/null; then g "RAM ${RAM_GB} GB (>= ${MIN_RAM_GB})"
else w "RAM ${RAM_GB} GB — ${MIN_RAM_GB}+ GB 권장"; fi
if has df; then
  DISK_GB=$(df -BG --output=avail "$DICOM_PATH" 2>/dev/null | tail -1 | tr -dc '0-9')
  [ -z "$DISK_GB" ] && DISK_GB=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9')
  if [ -n "$DISK_GB" ] && [ "$DISK_GB" -ge "$MIN_DISK_GB" ] 2>/dev/null; then g "디스크 여유 ${DISK_GB} GB (영상 저장: ${DICOM_PATH})"
  else w "디스크 여유 ${DISK_GB:-?} GB — 영상 보존(5년) 대비 ${MIN_DISK_GB}+ GB·전용 파티션 권장"; fi
fi

# ── 5. 시간 동기 / 로케일 ────────────────────────────────────────────────────
hdr "5. 시간 동기 / 타임존 / 로케일"
if has timedatectl; then
  SYNC=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
  [ "$SYNC" = "yes" ] && g "NTP 시간 동기됨" || w "NTP 미동기 — 판독 TAT/SLA/감사 시각 정확도 위해 chrony/ntp 권장"
  printf "        타임존: %s\n" "$(timedatectl show -p Timezone --value 2>/dev/null)"
else w "timedatectl 없음 — 시간 동기(NTP) 수동 확인"; fi
LANG_NOW="${LANG:-}"
echo "$LANG_NOW" | grep -qiE "utf-?8" && g "로케일 UTF-8 ($LANG_NOW)" || w "로케일 비-UTF8(${LANG_NOW:-미설정}) — ko_KR.UTF-8 권장(한글/리포트)"

# ── 6. TLS 인증서 (공개 도메인) ──────────────────────────────────────────────
hdr "6. TLS 인증서 (선택 — 운영 도메인 사용 시)"
TLS_CERT="${TLS_CERT:-}"
if [ -n "$TLS_CERT" ] && [ -r "$TLS_CERT" ]; then
  if has openssl; then
    END=$(openssl x509 -enddate -noout -in "$TLS_CERT" 2>/dev/null | cut -d= -f2)
    g "TLS 인증서 존재 (만료: ${END:-?})"
  else g "TLS 인증서 파일 존재 ($TLS_CERT)"; fi
else
  w "TLS 인증서 미지정 — Let's Encrypt 등으로 발급 필요(공개 서비스). TLS_CERT=<경로> 로 점검 가능"
fi

# ── 요약 ─────────────────────────────────────────────────────────────────────
hdr "결과 요약"
printf "  PASS=%d  WARN=%d  FAIL=%d\n" "$PASS" "$WARN" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf "\033[31m설치 전 FAIL 항목을 먼저 해결하세요.\033[0m\n"; exit 1
elif [ "$WARN" -gt 0 ]; then
  printf "\033[33mWARN 항목을 검토 후 진행하세요(운영은 해소 권장).\033[0m\n"; exit 0
else
  printf "\033[32m전제조건 충족 — 설치 진행 가능.\033[0m\n"; exit 0
fi
